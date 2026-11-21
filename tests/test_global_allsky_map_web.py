"""Installed architecture in a synthetic Flask/SQLite app; no listening server or devices."""
import copy
import re
import uuid
import unittest
from unittest.mock import Mock, patch
from flask import template_rendered, g
from flask_login import FlaskLoginClient

# Sets an explicitly temporary Flask configuration before importing the application.
from tests.test_global_allsky_map import APP, _TMP
from indi_allsky.flask import db
from indi_allsky.flask.models import (IndiAllSkyDbConfigTable, IndiAllSkyDbUserTable,
    IndiAllSkyDbCameraTable, IndiAllSkyDbStateTable, IndiAllSkyDbTaskQueueTable, TaskQueueState)
from indi_allsky.config import IndiAllSkyConfigBase
from indi_allsky.version import __config_level__
from indi_allsky import global_allsky_map as G


class GlobalMapWebTest(unittest.TestCase):
    IMAGE_URL = 'https://images.example.org/latest.jpg'

    def setUp(self):
        self.context=APP.app_context();self.context.push();db.create_all()
        APP.config.update(WTF_CSRF_ENABLED=False,SESSION_PROTECTION=None,LOGIN_DISABLED=False)
        APP.test_client_class=FlaskLoginClient
        self.user=IndiAllSkyDbUserTable(username='map-test',password='unused',email='test@example.invalid',
                                       name='Synthetic',active=True,staff=True,admin=True)
        db.session.add(self.user);db.session.flush()
        self.cfg=copy.deepcopy(IndiAllSkyConfigBase._base_config)
        self.cfg.update(VARLIB_FOLDER=_TMP.name,IMAGE_FOLDER=_TMP.name,IMAGE_EXPORT_FOLDER=_TMP.name,DETECT_MASK='')
        self.cfg['GLOBAL_ALLSKY_MAP'].update(ENABLE=True,IMAGE_URL=self.IMAGE_URL)
        entry=IndiAllSkyDbConfigTable(data=self.cfg,level=__config_level__,user_id=self.user.id,encrypted=False,note='fixture')
        db.session.add(entry);db.session.flush()
        camera=IndiAllSkyDbCameraTable(name='Generic test CCD',uuid=str(uuid.uuid4()),driver='indi_test',
            local=True,latitude=52.,longitude=0.,elevation=0,location='Synthetic',owner='Synthetic',
            lensName='Lens',lensFocalLength=1.55,lensFocalRatio=2.,width=1280,height=960,bits=8,alt=90.,az=0.,
            nightSunAlt=-6.,minGain=1.,maxGain=100.,minExposure=0.000001,maxExposure=300.,minBinning=1,maxBinning=4,data={'detected_name':'Automatically detected test CCD'})
        db.session.add(camera);db.session.flush()
        db.session.add_all([IndiAllSkyDbStateTable(key='DB_CAMERA_ID',value=str(camera.id)),
                            IndiAllSkyDbStateTable(key='CONFIG_ID',value=str(entry.id))]);db.session.commit()
        self.client=APP.test_client(user=self.user,fresh_login=True)
        self.block=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('External network forbidden'));self.block.start()
        self.endpoint='/indi-allsky/ajax/global_allsky_map'

    def tearDown(self):
        self.block.stop();db.session.remove();db.drop_all();self.context.pop()

    def preview(self):
        r=self.client.post(self.endpoint,json={'operation':'preview'})
        self.assertEqual(r.status_code,200,r.get_json());return r.get_json()

    def worker(self, task_id, response=None):
        from indi_allsky.video import VideoWorker
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);task.setQueued()
        worker=VideoWorker.__new__(VideoWorker);worker._miscDb=Mock()
        def send(data,opener=None,record=None):
            self.assertFalse(db.session().in_transaction())
            self.sent=data
            return response or {'ok':True,'status':'UPDATED','message':'1 5'}
        with patch.object(G,'post',side_effect=send) as call:
            worker.processTask({'task_id':task_id})
        return task,call

    def test_config_and_status_get_render_without_id_generation_or_network(self):
        r=self.client.get('/indi-allsky/config');self.assertEqual(r.status_code,200)
        self.assertIn(b'Allsky Map (Allsky project)',r.data)
        text = r.get_data(as_text=True)
        for tab_id, label in (('nav-global-allsky-map-tab', 'AllskyTeam Map'),
                              ('nav-allskymap-tab', 'Allsky Map')):
            tab = re.search(r'<button [^>]*id="' + tab_id + r'"[^>]*>(.*?)</button>',
                            text, re.S)
            self.assertIsNotNone(tab)
            self.assertEqual(re.sub(r'<[^>]+>', '', tab.group(1)).strip(), label)
            self.assertIn('tw:uppercase', tab.group(0))
        self.assertIn(b'GLOBAL_ALLSKY_MAP__IMAGE_URL',r.data)
        self.assertIn(b'GLOBAL_ALLSKY_MAP__WEBSITE_URL',r.data)
        with patch.object(G, 'post', side_effect=AssertionError('Status must not POST')) as post, \
                patch.object(G.GlobalMapService, 'enqueue', side_effect=AssertionError('Status must not enqueue')) as enqueue:
            for _ in range(3):
                self.assertEqual(self.client.get(self.endpoint).status_code,200)
            post.assert_not_called(); enqueue.assert_not_called()
        self.assertIsNone(G.GlobalMapService()._read(G.STATE_KEY))
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0)

    def test_status_refresh_preserves_established_state_and_request_ownership(self):
        service = G.GlobalMapService()
        preview = service.preview()
        service._change(lambda state: state.update(registered=True, publication_suppressed=True,
            needs_review=True, pending=987654, attempted_task=987654, payload_hash=preview['preview_token']))
        before = {row.key: row.value for row in IndiAllSkyDbStateTable.query.all()}
        configs = IndiAllSkyDbConfigTable.query.count()
        with patch.object(G, 'post', side_effect=AssertionError('Status must not POST')) as post, \
                patch.object(G.GlobalMapService, 'enqueue', side_effect=AssertionError('Status must not enqueue')) as enqueue:
            for _ in range(3):
                response = self.client.get(self.endpoint)
                self.assertEqual(response.status_code, 200)
                status = response.get_json()['status']
                self.assertTrue(status['needs_review'])
                self.assertTrue(status['publication_suppressed'])
                self.assertEqual(status['pending'], 987654)
            post.assert_not_called(); enqueue.assert_not_called()
        self.assertEqual({row.key: row.value for row in IndiAllSkyDbStateTable.query.all()}, before)
        self.assertEqual(IndiAllSkyDbConfigTable.query.count(), configs)
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_real_form_save_is_not_registration(self):
        captured=[]
        def receive(sender,template,context,**kw):
            if 'form_config' in context:captured.append(context['form_config'])
        with template_rendered.connected_to(receive,APP):r=self.client.get('/indi-allsky/config')
        data=copy.deepcopy(captured[-1].data)
        data.update(GLOBAL_ALLSKY_MAP__ENABLE=True,GLOBAL_ALLSKY_MAP__IMAGE_URL=self.IMAGE_URL,
                    GLOBAL_ALLSKY_MAP__EQUIPMENT='Synthetic heater',GLOBAL_ALLSKY_MAP__WEBSITE_URL='https://website.other.example/archive/',
                    RELOAD_ON_SAVE=False,CONFIG_NOTE='map test save')
        r=self.client.post('/indi-allsky/ajax/config',json=data)
        self.assertEqual(r.status_code,200,r.get_json())
        latest=IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        self.assertEqual(latest.data['GLOBAL_ALLSKY_MAP']['IMAGE_URL'],self.IMAGE_URL)
        self.assertEqual(latest.data['GLOBAL_ALLSKY_MAP']['EQUIPMENT'],'Synthetic heater')
        self.assertEqual(latest.data['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'], 'https://website.other.example/archive/')
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0)

    def test_preview_explicit_registration_and_actual_video_dispatch(self):
        preview=self.preview();self.assertEqual(preview['metadata']['image_url'],self.IMAGE_URL)
        self.assertEqual(preview['metadata']['website_url'],'')
        self.assertEqual(preview['metadata']['allsky_settings'],{'equipmentinfo':''})
        r=self.client.post(self.endpoint,json={'operation':'register','preview_token':preview['preview_token']})
        self.assertEqual(r.status_code,200,r.get_json())
        task,call=self.worker(r.get_json()['task_id'])
        self.assertEqual(task.state,TaskQueueState.SUCCESS);self.assertEqual(call.call_count,1)
        self.assertFalse(self.sent['force']);self.assertEqual(self.sent['image_url'],self.IMAGE_URL)
        self.assertTrue(G.GlobalMapService().state()['registered'])

    def test_unconfigured_location_owner_preview_and_worker_preserve_saved_config(self):
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        config = copy.deepcopy(entry.data)
        config.pop('LOCATION_NAME', None)
        config['OWNER'] = None
        entry.data = config
        db.session.commit()
        original = copy.deepcopy(entry.data)
        preview = self.preview()
        self.assertEqual(preview['metadata']['location'], 'Unknown')
        self.assertEqual(preview['metadata']['owner'], 'Unknown')
        response = self.client.post(self.endpoint, json={'operation': 'register',
            'preview_token': preview['preview_token']})
        self.assertEqual(response.status_code, 200)
        task, call = self.worker(response.get_json()['task_id'])
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.sent['location'], preview['metadata']['location'])
        self.assertEqual(self.sent['owner'], preview['metadata']['owner'])
        self.assertEqual(db.session.get(IndiAllSkyDbConfigTable, entry.id).data, original)

    def test_different_domain_preview_and_worker_preserve_both_urls(self):
        website = 'https://website.other.example:8443/Archive/?view=sky'
        image = 'https://images.example.org/Latest.JPG?raw=1'
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        cfg = copy.deepcopy(entry.data)
        cfg['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'] = website
        cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'] = image
        entry.data = cfg
        db.session.commit()
        page = self.client.get('/indi-allsky/config')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'May be on a different domain from the website', page.data)
        preview = self.preview()
        self.assertEqual(preview['metadata']['website_url'], website)
        self.assertEqual(preview['metadata']['image_url'], image)
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        self.assertEqual(response.status_code, 200, response.get_json())
        task, call = self.worker(response.get_json()['task_id'])
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.sent['website_url'], website)
        self.assertEqual(self.sent['image_url'], image)

    def _accuracy_form_data(self):
        captured = []
        def receive(sender, template, context, **kwargs):
            if 'form_config' in context:
                captured.append(context['form_config'])
        with template_rendered.connected_to(receive, APP):
            response = self.client.get('/indi-allsky/config')
        self.assertEqual(response.status_code, 200)
        data = copy.deepcopy(captured[-1].data)
        data.update(RELOAD_ON_SAVE=False, CONFIG_NOTE='Synthetic accuracy test')
        return data, response.data

    def test_accuracy_old_config_defaults_to_legacy_without_publication(self):
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        cfg = copy.deepcopy(entry.data)
        cfg['GLOBAL_ALLSKY_MAP'].pop('LOCATION_ACCURACY', None)
        entry.data = cfg
        db.session.commit()
        data, page = self._accuracy_form_data()
        self.assertEqual(data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'], 'legacy')
        self.assertIn(b'Round to 2 decimal places (default)', page)
        self.assertIn(b'Exact saved location', page)
        data.pop('GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY')
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
        self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], 'legacy')
        self.assertEqual(saved['LOCATION_LATITUDE'], cfg['LOCATION_LATITUDE'])
        self.assertEqual(saved['LOCATION_LONGITUDE'], cfg['LOCATION_LONGITUDE'])
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_accuracy_saving_pre_feature_config_does_not_change_upgrade_default(self):
        # The generic config loader shallow-copies base config. Isolate this feature's
        # default section so this test cannot leak a deliberately mutated template.
        section = copy.deepcopy(IndiAllSkyConfigBase._base_config['GLOBAL_ALLSKY_MAP'])
        with patch.dict(IndiAllSkyConfigBase._base_config, GLOBAL_ALLSKY_MAP=section):
            entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
            old = copy.deepcopy(entry.data)
            old.pop('GLOBAL_ALLSKY_MAP')
            entry.data = old
            db.session.commit()
            data, _ = self._accuracy_form_data()
            self.assertEqual(data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'], 'legacy')
            data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'] = 'exact'
            response = self.client.post('/indi-allsky/ajax/config', json=data)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(section['LOCATION_ACCURACY'], 'legacy')
            newest = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
            newest.data = copy.deepcopy(old)
            db.session.commit()
            data, _ = self._accuracy_form_data()
            self.assertEqual(data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'], 'legacy')

    def test_accuracy_choices_save_and_omitted_choice_is_preserved(self):
        for mode in ['legacy', 'exact', '0.5km', '1km', '2km', '5km']:
            data, _ = self._accuracy_form_data()
            data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'] = mode
            response = self.client.post('/indi-allsky/ajax/config', json=data)
            self.assertEqual(response.status_code, 200, response.get_json())
            saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
            self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], mode)
        data, _ = self._accuracy_form_data()
        data.pop('GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY')
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
        self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], '5km')
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_accuracy_invalid_form_choice_is_rejected(self):
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'] = 'unknown'
        count = IndiAllSkyDbConfigTable.query.count()
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn('GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY', response.get_json())
        self.assertEqual(IndiAllSkyDbConfigTable.query.count(), count)
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_accuracy_private_save_ignores_changes_preserves_choice_and_preview(self):
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        cfg = copy.deepcopy(entry.data)
        cfg.update(PRIVACY_MODE=True, LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654)
        cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = '1km'
        entry.data = cfg
        db.session.commit()
        data, page = self._accuracy_form_data()
        select = re.search(rb'<select[^>]*id="GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY"[^>]*>', page).group()
        self.assertIn(b'disabled', select)
        self.assertIn(b'this setting has no effect', page)
        self.assertEqual(data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'], '1km')
        # A crafted supported finer choice cannot bypass or replace the dormant setting.
        data['GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY'] = 'exact'
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
        self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], '1km')
        preview = self.preview()['metadata']
        self.assertEqual((preview['latitude'], preview['longitude']), ('35N', '13E'))
        self.assertNotIn('35.123', str(preview))
        data, _ = self._accuracy_form_data()
        data.pop('GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY')
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        data, _ = self._accuracy_form_data()
        data['PRIVACY_MODE'] = False
        data.pop('GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY')
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
        self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], '1km')
        expected = G.publication_coordinates(saved['LOCATION_LATITUDE'], saved['LOCATION_LONGITUDE'], False, '1km')
        preview = self.preview()['metadata']
        self.assertEqual((preview['latitude'], preview['longitude']), expected)
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_accuracy_private_toggle_javascript_disables_and_restores_control(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is needed for the isolated UI-handler test')
        _, page = self._accuracy_form_data()
        function = re.search(rb'function updateLocationPrivacy\(\) \{.*?\n  \}', page, re.S).group().decode()
        harness = r"""
const assert = require('node:assert/strict');
let checked = false, disabled = null, visible = null, callback;
const $ = selector => ({
  prop(name, value) {
    if (selector === '#PRIVACY_MODE') return checked;
    assert.equal(selector, '#GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY');
    assert.equal(name, 'disabled'); disabled = value;
  },
  toggle(value) { assert.equal(selector, '#global-map-private-location'); visible = value; },
  on(event, handler) { assert.equal(event, 'change'); callback = handler; }
});
"""
        harness += function + "\n$('#PRIVACY_MODE').on('change', updateLocationPrivacy); updateLocationPrivacy();\n"
        harness += "assert.equal(disabled,false); assert.equal(visible,false); checked=true; callback(); assert.equal(disabled,true); assert.equal(visible,true); checked=false; callback(); assert.equal(disabled,false); assert.equal(visible,false);"
        result = subprocess.run([node, '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accuracy_preview_and_worker_use_saved_choice_without_extra_payload_fields(self):
        data, _ = self._accuracy_form_data()
        data.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654,
                    GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY='exact')
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        preview = self.preview()
        self.assertEqual((preview['metadata']['latitude'], preview['metadata']['longitude']), ('35.123N', '12.654E'))
        response = self.client.post(self.endpoint, json={'operation': 'register', 'preview_token': preview['preview_token']})
        self.assertEqual(response.status_code, 200, response.get_json())
        task, call = self.worker(response.get_json()['task_id'])
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertEqual(call.call_count, 1)
        self.assertEqual((self.sent['latitude'], self.sent['longitude']), ('35.123N', '12.654E'))
        self.assertNotIn('LOCATION_ACCURACY', self.sent)

    def test_worker_uses_fresh_config_after_disable(self):
        preview=self.preview();r=self.client.post(self.endpoint,json={'operation':'register','preview_token':preview['preview_token']})
        entry=IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        cfg=copy.deepcopy(entry.data);cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=False;entry.data=cfg;db.session.commit()
        task,call=self.worker(r.get_json()['task_id'])
        self.assertEqual(task.state,TaskQueueState.FAILED);self.assertEqual(call.call_count,0)

    def test_remove_and_disable_is_combined_and_preserves_identity(self):
        preview=self.preview();r=self.client.post(self.endpoint,json={'operation':'register','preview_token':preview['preview_token']})
        self.worker(r.get_json()['task_id']);identifier=G.GlobalMapService().identifier()
        r=self.client.post(self.endpoint,json={'operation':'remove','confirm':True})
        self.assertEqual(r.status_code,200,r.get_json())
        self.assertFalse(r.get_json()['enabled'])
        task,call=self.worker(r.get_json()['task_id'],{'ok':True,'status':'DELETED','message':''})
        self.assertEqual(task.state,TaskQueueState.SUCCESS)
        self.assertEqual(self.sent,{'machine_id':identifier,'website_url':'DELETE'})
        self.assertFalse(G.GlobalMapService().state()['registered'])
        self.assertEqual(G.GlobalMapService().identifier(),identifier)

    def test_authentication_admin_and_force_confirmation(self):
        self.assertEqual(APP.test_client().get(self.endpoint).status_code,302)
        g.pop('_login_user',None)
        self.user.admin=False;db.session.commit()
        self.assertEqual(self.client.get(self.endpoint).status_code,403)
        self.assertEqual(self.client.post(self.endpoint,json={'operation':'preview'}).status_code,403)
        self.user.admin=True;db.session.commit()
        self.assertEqual(self.client.post(self.endpoint,json={'operation':'force'}).status_code,400)
        self.assertEqual(self.client.post(self.endpoint,json={'operation':'remove'}).status_code,400)

    def test_invalid_json_is_rejected_without_side_effects(self):
        self.assertEqual(self.client.post(self.endpoint,json=['preview']).status_code,400)
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0)

    def test_csrf_protection_on_actual_endpoint(self):
        APP.config['WTF_CSRF_ENABLED']=True
        r=self.client.post(self.endpoint,json={'operation':'preview'})
        self.assertEqual(r.status_code,400)
        page=self.client.get('/indi-allsky/config');self.assertEqual(page.status_code,200)
        token=re.search(rb'X-CSRFToken", "([^"]+)"',page.data).group(1).decode()
        r=self.client.post(self.endpoint,json={'operation':'preview'},headers={'X-CSRFToken':token})
        self.assertEqual(r.status_code,200,r.get_json())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0)


    def test_shared_metadata_consent_notice_is_rendered(self):
        page = self.client.get('/indi-allsky/config')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Listings are public', page.data)
        self.assertIn(b'soon after any published detail changes', page.data)
        self.assertIn(b'an INDI-AllSky upgrade', page.data)

    def test_presentation_documentation_hooks_and_no_render_side_effects(self):
        service = G.GlobalMapService()
        self.assertIsNone(service.identifier())
        page = self.client.get('/indi-allsky/config')
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('https://github.com/aaronwmorris/indi-allsky/wiki/Global-Allsky-Map', text)
        map_link = re.search(r'<a [^>]*href="https://www\.thomasjacquin\.com/allsky-map/"[^>]*>View Allsky Map</a>', text)
        self.assertIsNotNone(map_link)
        self.assertIn('target="_blank"', map_link.group())
        self.assertIn('rel="noopener"', map_link.group())
        self.assertNotIn('onclick', map_link.group())
        self.assertNotIn('data-global-map', map_link.group())
        introduction = re.search(r'<section id="global-map-introduction"[^>]*>(.*?)</section>', text, re.S)
        self.assertIsNotNone(introduction)
        self.assertIn('<strong>AllskyTeam Map</strong> is the global camera map created by Thomas Jacquin for the Allsky project.', introduction.group())
        self.assertIn('This integration allows your indi-allsky camera to publish its location and details to the map.', introduction.group())
        self.assertIn('to the map. You can optionally provide a publicly accessible URL for your latest image.</p>', introduction.group())
        self.assertNotIn('<strong>You can optionally provide', introduction.group())
        self.assertIn('tw:card tw:bg-base-200 tw:border tw:border-base-300', introduction.group())
        self.assertNotRegex(introduction.group(), r'tw:alert|<a |<button|<input')
        panel_start = text.index('id="nav-global-allsky-map" role="tabpanel"')
        first_section = text.index('<section', panel_start)
        self.assertEqual(first_section, introduction.start())
        self.assertLess(text.index('id="save-button"'), introduction.start())
        following = text[introduction.end():]
        self.assertRegex(following, r'^\s*<section class="tw:card')
        self.assertLess(introduction.end(), text.index('Allsky Map (Allsky project)', panel_start))
        self.assertEqual(text.count('id="global-map-introduction"'), 1)
        self.assertIn('Also published', text)
        self.assertIn('Technical details', text)
        self.assertIn('How publishing works', text)
        self.assertIn('First listings are normally created with Register / Update', text)
        self.assertIn('one-minute guard', text)
        self.assertIn('Publication preview', text)
        self.assertNotIn('Preview — not yet sent', text)
        self.assertIn('limited by the precision of your saved location', text)
        self.assertNotIn('then respect source precision', text)
        for name in ['ENABLE', 'LOCATION_ACCURACY', 'WEBSITE_URL', 'IMAGE_URL', 'EQUIPMENT']:
            self.assertEqual(text.count('id="GLOBAL_ALLSKY_MAP__' + name + '"'), 1)
            self.assertEqual(text.count('id="GLOBAL_ALLSKY_MAP__' + name + '-error"'), 1)
        for op in ['preview', 'register', 'force', 'remove']:
            self.assertIn('data-global-map="' + op + '"', text)
        for op in ['register', 'force']:
            self.assertRegex(text, r'<button[^>]*data-global-map="' + op + r'"[^>]*disabled')
        self.assertNotRegex(text, r'<button[^>]*data-global-map="remove"[^>]*disabled')
        for element in ['global-map-private-location', 'global-map-preview', 'global-map-status', 'global-map-refresh']:
            self.assertEqual(text.count('id="' + element + '"'), 1)
        self.assertIn('tw:sm:grid-cols-2', text)
        self.assertIn('overflow-wrap:anywhere', text)
        self.assertIn('width:min(10rem, 40%)', text)
        self.assertIn('Keep it private. Anyone with it could change or remove your listing.', text)
        self.assertIn('is not used to log in to indi-allsky', text)
        self.assertIn('new MutationObserver(loadGlobalMapStatusOnOpen)', text)
        self.assertNotIn('.html(', text[text.index('function renderGlobalMapStatus'):text.index('function show(data)')])
        self.assertIsNone(service.identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_presentation_wiki_single_source_and_policy_wording(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        page = (root / 'docs/wiki/Global-Allsky-Map.md').read_text()
        self.assertFalse((root / 'docs/global-allsky-map.md').exists())
        self.assertIn('[Allsky Map (Allsky project)](Global-Allsky-Map)',
                      (root / 'docs/wiki/Home.md').read_text())
        for phrase in ['5 ordinary attempts in any 24 hours', 'a rolling window', 'one-minute gap',
                       'Effect on marker position', 'not guaranteed for every location',
                       'database** backups', 'different domains', 'Keep it private.',
                       'at least 24 hours', "won't necessarily clear the pending or review status",
                       "the rebuild itself doesn't register anything"]:
            self.assertIn(phrase, page)
        self.assertNotIn('For developers:', page)
        self.assertNotIn('near the poles', page)
        self.assertIn('Location name and Owner are published as `Unknown`', page)
        intro = page.split('## Quick start')[0]
        self.assertNotIn('Force and Remove also send requests', intro)
        self.assertIn('Once registered, changes can be published automatically while publication is enabled and active.', page)
        self.assertIn('saved changes can be published before you Preview them', page)
        for lat, lon in [(35.123, 12.654), (35.1, 12.6)]:
            cells = [', '.join(G.publication_coordinates(lat, lon, False, mode))
                     for mode in ['legacy', '1km', '5km']]
            self.assertIn('| ' + str(lat) + ', ' + str(lon) + ' | ' + ' | '.join(cells) + ' |', page)
        for message in ['Preview the saved metadata before publication',
                        'Publication suppressed; Preview and explicitly Register to resume',
                        'Five ordinary attempts in the last 24 hours; wait for quota or explicitly force an update',
                        'Wait one minute between map requests',
                        'A different map request is pending; wait for it to finish',
                        'No active local camera metadata is available']:
            self.assertIn(message, page)
        headings = {re.sub(r'[^\w -]', '', line.lstrip('# ').lower()).replace(' ', '-')
                    for line in page.splitlines() if line.startswith('#')}
        for anchor in re.findall(r'\]\(#([^)]*)\)', page):
            self.assertIn(anchor, headings)

    def test_status_and_preview_renderers_use_literal_text(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node is needed for the isolated summary-renderer test')
        _, page = self._accuracy_form_data()
        source = page.decode()
        status_fn = re.search(r'  function renderGlobalMapStatus\(data\) \{.*?\n  \}', source, re.S).group()
        preview_fn = re.search(r'  function renderGlobalMapPreview\(metadata\) \{.*?\n  \}', source, re.S).group()
        result_fn = re.search(r'  function globalMapLastResult\(value\) \{.*?\n  \}', source, re.S).group()
        load_fn = re.search(r'  function loadGlobalMapStatus\(\) \{.*?\n  \}', source, re.S).group()
        action_handler = re.search(r"  buttons\.on\('click', function \(\) \{.*?\n  \}\);", source, re.S).group()
        activation = re.search(r"  \$\('#global-map-refresh'\).on\('click', loadGlobalMapStatus\);.*?  loadGlobalMapStatusOnOpen\(\);", source, re.S).group()
        harness = r"""
const assert = require('node:assert/strict');
let savedEnabled = true;
const elements = new Map();
class Element {
  constructor() { this.children = []; this.value = ''; this.classes = ''; }
  empty() { this.children = []; return this; }
  text(value) { this.value = String(value); return this; }
  addClass(value) { this.classes += value; return this; }
  appendTo(parent) { parent.children.push(this); return this; }
  show() { this.visible = true; return this; }
  on(event, handler) { this.handlers = this.handlers || {}; this.handlers[event] = handler; return this; }
  prop(name, value) { this.props = this.props || {}; if (arguments.length === 1) return this.props[name]; this.props[name] = value; return this; }
  html() { throw new Error('HTML insertion forbidden'); }
}
const $ = selector => {
  if (typeof selector !== 'string') return selector;
  if (selector.startsWith('<')) return new Element();
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
const labels = () => $('#global-map-badges').children.map(x => x.value);
"""
        harness += result_fn + '\n' + status_fn + '\n' + preview_fn + r"""
renderGlobalMapStatus({enabled:true,status:{registered:true,publication_suppressed:true,needs_review:true,pending:42,dirty:true,last_success:1800000000,quota:{updates:2,maximum:5},last_status:'<b>unsafe</b>'}});
assert.deepEqual(labels(), ['Registered','Publishing paused','Needs review','Request pending','Changes not yet published']);
assert.ok($('#global-map-summary').children.some(x => x.value === 'Last result: <b>unsafe</b>'));
assert.ok($('#global-map-summary').children.some(x => x.value.includes('2 of 5 (at last response)')));
renderGlobalMapStatus({enabled:false,status:{registered:null}});
assert.deepEqual(labels(), ['Not registered','Publishing off']);
renderGlobalMapStatus({enabled:true,status:{registered:true,needs_review:true}});
assert.deepEqual(labels(), ['Registered','Needs review']);
renderGlobalMapStatus({enabled:true,status:{registered:true}});
assert.deepEqual(labels(), ['Registered','Publishing active']);
renderGlobalMapStatus({enabled:false,status:{registered:false,last_status:'DELETED'}});
assert.deepEqual(labels(), ['Removed','Publishing off']);
renderGlobalMapStatus({error:'<b>failed</b>'});
assert.equal($('#global-map-error').value, '<b>failed</b>');
renderGlobalMapPreview({latitude:'35.12N',longitude:'12.65E',owner:'<b>owner</b>',equipmentinfo:'',machine_id:'hidden'});
const rows = $('#global-map-preview-rows').children;
assert.equal(rows.length, 10);
assert.deepEqual(rows[0].children.map(x => x.value), ['Coordinates','35.12N, 12.65E']);
assert.equal(rows[2].children[1].value, '<b>owner</b>');
assert.equal(rows[8].children[1].value, '—');
assert.ok(!rows.some(row => row.children[0].value === 'machine_id'));
assert.equal($('#global-map-preview-panel').visible, true);
assert.equal($('#global-map-preview-heading').value, 'Publication preview');
const known = {INSERTED:'Registered', UPDATED:'Updated', DELETED:'Removed', ALREADY_UPDATED:'Server update limit reached', ERROR:'Server error', FAILED:'Failed', STALE:'Not sent — saved details changed', DISABLED:'Not sent — publication disabled or paused', NOT_SENT:'Not sent'};
for (const [code,label] of Object.entries(known)) assert.equal(globalMapLastResult(code + ': detail'), label);
assert.equal(globalMapLastResult('Queued register'), 'Request queued');
assert.equal(globalMapLastResult('Sending update'), 'Sending request');
assert.equal(globalMapLastResult('Interrupted request; manual review required, not retried'), 'Interrupted request — review required');
assert.equal(globalMapLastResult('UPDATEDNESS: unexpected'), 'UPDATEDNESS: unexpected');
assert.equal(globalMapLastResult('Unknown <b>message</b>'), 'Unknown <b>message</b>');
const raw = {enabled:true,status:{registered:true,last_status:'UPDATED: 1 5',response_evidence:{body:'RETURN UPDATED 1 5\n',http_status:200}}};
renderGlobalMapStatus(raw);
assert.ok($('#global-map-summary').children.some(x => x.value === 'Last result: Updated'));
assert.deepEqual(JSON.parse($('#global-map-status').value), raw);
const fingerprint = 'ab'.repeat(32);
const previewResponse = {metadata:{latitude:'35.12N',longitude:'12.65E',machine_id:'(installation identifier hidden)'},preview_token:fingerprint,status:raw.status};
const originalResponse = JSON.stringify(previewResponse);
renderGlobalMapStatus(previewResponse);
const displayed = JSON.parse($('#global-map-status').value);
assert.equal(displayed.preview_token,'(preview fingerprint hidden)');
assert.ok(!$('#global-map-status').value.includes(fingerprint));
assert.deepEqual(displayed.metadata,previewResponse.metadata);
assert.deepEqual(displayed.status,raw.status);
assert.equal(JSON.stringify(previewResponse),originalResponse);

let localGets = 0, tabActive = false, observerCallback, lastDone, lastFail;
const endpoint = '/indi-allsky/ajax/global_allsky_map';
const panel = {style:{display:'none'},classList:{contains(name) { assert.equal(name,'active'); return tabActive; }}};
const document = {getElementById(id) { assert.equal(id,'nav-global-allsky-map'); return panel; }};
class MutationObserver {
  constructor(callback) { observerCallback = callback; }
  observe(target, options) { assert.equal(target,panel); assert.deepEqual(options,{attributes:true,attributeFilter:['class','style']}); }
}
$.getJSON = url => {
  assert.equal(url,endpoint); localGets++;
  return {done(fn) { lastDone = fn; return this; }, fail(fn) { lastFail = fn; return this; }};
};
const show = renderGlobalMapStatus;
"""
        harness += load_fn + '\n' + activation + r"""
assert.equal(localGets,0);
tabActive = true; panel.style.display = 'block'; observerCallback();
assert.equal(localGets,1);
observerCallback(); assert.equal(localGets,1);
lastDone(raw); assert.deepEqual(JSON.parse($('#global-map-status').value),raw);
tabActive = false; panel.style.display = 'none'; observerCallback(); assert.equal(localGets,1);
tabActive = true; panel.style.display = 'block'; observerCallback(); assert.equal(localGets,2);
$('#global-map-refresh').handlers.click(); assert.equal(localGets,3);
lastFail({responseJSON:{error:'Synthetic status failure'}});
assert.equal($('#global-map-error').value,'Synthetic status failure');
// If a tab was already active when this script initialized, its initial check loads too.
statusPanelWasVisible = false; loadGlobalMapStatusOnOpen(); assert.equal(localGets,4);
"""
        harness += r"""
let previewToken = null;
const buttons = new Element();
const requests = [];
let response = previewResponse;
$.ajax = options => {
  assert.equal(options.url,endpoint);
  assert.equal(options.method,'POST');
  requests.push(JSON.parse(options.data));
  return {done(fn) { fn(response); return this; },fail(fn) { return this; },always(fn) { fn(); return this; }};
};
""" + action_handler + r"""
buttons.handlers.click.call({data(name) { assert.equal(name,'global-map'); return 'preview'; }});
assert.equal(previewToken,fingerprint);
assert.equal(JSON.parse($('#global-map-status').value).preview_token,'(preview fingerprint hidden)');
assert.ok(!$('#global-map-status').value.includes(fingerprint));
response = {task_id:42,status:raw.status};
buttons.handlers.click.call({data(name) { assert.equal(name,'global-map'); return 'register'; }});
assert.equal(requests[1].preview_token,fingerprint);
assert.equal(requests[1].operation,'register');
assert.equal(previewResponse.preview_token,fingerprint);
assert.deepEqual(JSON.parse($('#global-map-status').value),response);
"""
        result = subprocess.run([node, '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_common_form_validator_rejects_proxy_only_when_enabled(self):
        from types import SimpleNamespace
        from wtforms.validators import ValidationError
        from indi_allsky.flask.forms import GLOBAL_ALLSKY_MAP_urls_validator
        form = SimpleNamespace(GLOBAL_ALLSKY_MAP__WEBSITE_URL=SimpleNamespace(data=''),
            GLOBAL_ALLSKY_MAP__IMAGE_URL=SimpleNamespace(data='https://CDN.ALLSKY-MAP.COM./image'),
            GLOBAL_ALLSKY_MAP__ENABLE=SimpleNamespace(data=True))
        with self.assertRaises(ValidationError):
            GLOBAL_ALLSKY_MAP_urls_validator(form, None)
        form.GLOBAL_ALLSKY_MAP__ENABLE.data = False
        GLOBAL_ALLSKY_MAP_urls_validator(form, None)
        # Disabled form saving does not turn a forbidden URL into publishable metadata.
        self.cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'] = form.GLOBAL_ALLSKY_MAP__IMAGE_URL.data
        with self.assertRaises(G.MapError):
            G.payload(self.cfg, IndiAllSkyDbCameraTable.query.first(), 'a' * 32)

    def test_worker_unexpected_execute_failure_is_terminal_and_worker_continues(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setQueued()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        with patch.object(G.GlobalMapService, 'execute', side_effect=RuntimeError('private error')):
            worker.processTask({'task_id': task.id})
        self.assertEqual(task.state, TaskQueueState.FAILED)
        # An unrelated next task can still be dispatched in the same worker object.
        from indi_allsky.flask.models import TaskQueueQueue
        following = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.VIDEO,
            state=TaskQueueState.QUEUED, priority=100, data={'action': 'syntheticFollowingTask'})
        db.session.add(following)
        db.session.commit()
        worker.syntheticFollowingTask = Mock(side_effect=lambda job: job.setSuccess('Completed'))
        worker.processTask({'task_id': following.id})
        self.assertEqual(following.state, TaskQueueState.SUCCESS)
        self.assertTrue(G.GlobalMapService().status()['pending'])

    def test_worker_finish_failure_retains_claim_and_surfaces_review(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setQueued()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        original = G.GlobalMapService._change
        def fail_finish(service, change):
            if change.__name__ == 'finish':
                raise RuntimeError('finish unavailable')
            return original(service, change)
        with patch.object(G, 'post', return_value={'ok': True, 'status': 'UPDATED', 'message': ''}) as post, \
                patch.object(G.GlobalMapService, '_change', new=fail_finish):
            worker.processTask({'task_id': task.id})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(task.state, TaskQueueState.FAILED)
        state = G.GlobalMapService().state()
        self.assertEqual(state['attempted_task'], task.id)
        self.assertEqual(state['pending'], task.id)
        self.assertTrue(G.GlobalMapService().status()['needs_review'])
        self.assertIsNone(G.GlobalMapService().schedule())

    def test_worker_terminalisation_failure_preserves_committed_success(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setQueued()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        original = IndiAllSkyDbTaskQueueTable.setSuccess
        def committed_then_error(job, message):
            original(job, message)
            raise RuntimeError('after success commit')
        with patch.object(G, 'post', return_value={'ok': True, 'status': 'UPDATED', 'message': ''}), \
                patch.object(IndiAllSkyDbTaskQueueTable, 'setSuccess', new=committed_then_error):
            worker.processTask({'task_id': task.id})
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertTrue(G.GlobalMapService().state()['registered'])

    def test_worker_notification_failure_does_not_downgrade_success(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setQueued()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        worker._miscDb.clearNotification.side_effect = RuntimeError('private notification error')
        with patch.object(G, 'post', return_value={'ok': True, 'status': 'UPDATED', 'message': ''}):
            worker.processTask({'task_id': task.id})
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertTrue(G.GlobalMapService().state()['registered'])
        self.assertNotIn('pending', G.GlobalMapService().state())

    def test_worker_persistent_cleanup_failure_is_contained_without_false_success(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setRunning()
        service = G.GlobalMapService()
        service._change(lambda state: state.update(attempted_task=task.id, last_status='Sending register'))
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        with patch.object(G.GlobalMapService, 'execute', side_effect=RuntimeError('db unavailable')), \
                patch.object(db.session, 'rollback', side_effect=RuntimeError('rollback unavailable')):
            worker.publishGlobalAllskyMap(task, **task.data['kwargs'])
        self.assertEqual(task.state, TaskQueueState.RUNNING)
        self.assertEqual(service.state()['attempted_task'], task.id)
        self.assertEqual(service.state()['pending'], task.id)
        self.assertFalse(service.state().get('registered'))

    def test_worker_failed_task_persistence_is_contained_and_logs_only_types(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setRunning()
        service = G.GlobalMapService()
        service._change(lambda state: state.update(attempted_task=task.id, last_status='Sending register'))
        identifier = service.identifier()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        with self.assertLogs('indi_allsky', level='ERROR') as logs, \
                patch.object(G.GlobalMapService, 'execute', side_effect=RuntimeError('private ' + identifier)), \
                patch.object(IndiAllSkyDbTaskQueueTable, 'setFailed', side_effect=RuntimeError('private ' + identifier)):
            worker.publishGlobalAllskyMap(task, **task.data['kwargs'])
        self.assertNotIn(identifier, str(logs.output))
        self.assertNotIn('private', str(logs.output))
        self.assertIn('RuntimeError', str(logs.output))
        self.assertEqual(task.state, TaskQueueState.RUNNING)
        self.assertEqual(service.state()['attempted_task'], task.id)
        self.assertEqual(service.state()['pending'], task.id)

    def test_worker_uncommitted_terminalisation_failure_is_best_effort_failed(self):
        from indi_allsky.video import VideoWorker
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation': 'register',
                                                       'preview_token': preview['preview_token']})
        task = db.session.get(IndiAllSkyDbTaskQueueTable, response.get_json()['task_id'])
        task.setQueued()
        worker = VideoWorker.__new__(VideoWorker)
        worker._miscDb = Mock()
        with patch.object(G, 'post', return_value={'ok': True, 'status': 'UPDATED', 'message': ''}), \
                patch.object(IndiAllSkyDbTaskQueueTable, 'setSuccess', side_effect=RuntimeError('commit failed')):
            worker.processTask({'task_id': task.id})
        self.assertEqual(task.state, TaskQueueState.FAILED)
        # A durable server success is retained even though task terminalisation failed.
        self.assertTrue(G.GlobalMapService().state()['registered'])



    def _write_stale_config(self, stale, relocation=False):
        # Actual core updater on a synthetic parent: save only into this test DB.
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        from indi_allsky.config import IndiAllSkyConfig, ConfigSaveException
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'indi_allsky/allsky.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'IndiAllSky')
        method = next(n for n in cls.body if getattr(n, 'name', None) == ('updateConfigLocation' if relocation else 'updateConfigPaused'))
        from sqlalchemy.orm.exc import NoResultFound
        ns = {'logger': Mock(), 'ConfigSaveException': ConfigSaveException,
              'db': db, 'IndiAllSkyDbCameraTable': IndiAllSkyDbCameraTable, 'NoResultFound': NoResultFound}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<synthetic parent>', 'exec'), ns)
        if IndiAllSkyDbUserTable.query.filter_by(username='system').first() is None:
            db.session.add(IndiAllSkyDbUserTable(username='system', password='unused', email='system@example.invalid',
                name='Synthetic system actor', active=True, staff=False, admin=False))
            db.session.commit()
        config_obj = IndiAllSkyConfig()
        config_obj.config = copy.deepcopy(stale)
        parent = SimpleNamespace(config=config_obj.config, _config_obj=config_obj)
        if relocation:
            ns['updateConfigLocation'](parent, 40.125, 15.625, 100, IndiAllSkyDbCameraTable.query.first().id)
        else:
            ns['updateConfigPaused'](parent, True)
        self.assertTrue(IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data['GLOBAL_ALLSKY_MAP']['ENABLE'])

    def test_disabled_form_save_survives_actual_parent_stale_writeback(self):
        self.preview()
        service = G.GlobalMapService()
        service._change(lambda state: state.update(registered=True, needs_review=False, last_success=0))
        stale = copy.deepcopy(self.cfg)
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        self._write_stale_config(stale)
        self.assertTrue(service.status()['publication_suppressed'])
        self.assertIsNone(service.schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)
        # Explicit Enable alone is not token-bound resumption.
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = True
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        self.assertTrue(service.state()['publication_suppressed'])
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation':'register','preview_token':preview['preview_token']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(service.state()['publication_suppressed'])
        task, call = self.worker(response.get_json()['task_id'])
        self.assertEqual(call.call_count, 1)
        self.assertEqual(task.state, TaskQueueState.SUCCESS)

    def test_remove_refusal_and_old_success_preserve_disable_after_stale_writeback(self):
        preview = self.preview()
        response = self.client.post(self.endpoint, json={'operation':'register','preview_token':preview['preview_token']})
        task_id = response.get_json()['task_id']
        stale = copy.deepcopy(self.cfg)
        def remove_during_post(data, opener=None, record=None):
            response = self.client.post(self.endpoint, json={'operation':'remove','confirm':True})
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.get_json()['enabled'])
            return {'ok':True,'status':'UPDATED','message':''}
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        with patch.object(G, 'post', side_effect=remove_during_post):
            G.GlobalMapService().execute(task, **task.data['kwargs'])
        self._write_stale_config(stale)
        service = G.GlobalMapService()
        self.assertTrue(service.state()['registered'])
        self.assertTrue(service.state()['publication_suppressed'])
        self.assertIsNone(service.schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 1)

    def test_disabled_form_save_failure_retains_safe_suppression(self):
        self.preview()
        from indi_allsky.config import IndiAllSkyConfig, ConfigSaveException
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        with patch.object(IndiAllSkyConfig, 'save', side_effect=ConfigSaveException('synthetic save failure')):
            response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(G.GlobalMapService().state()['publication_suppressed'])
        self.assertTrue(G.GlobalMapService().config()['GLOBAL_ALLSKY_MAP']['ENABLE'])

    def test_suppression_failure_prevents_config_save_or_false_success(self):
        self.preview()
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        count = IndiAllSkyDbConfigTable.query.count()
        with patch.object(G.GlobalMapService, 'suppress_publication', side_effect=G.MapError('synthetic state busy')):
            response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(IndiAllSkyDbConfigTable.query.count(), count)

    def test_private_and_nonprivate_pre_feature_saves_leave_all_defaults_unchanged(self):
        defaults = copy.deepcopy(IndiAllSkyConfigBase._base_config['GLOBAL_ALLSKY_MAP'])
        for private in [True, False]:
            entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
            old = copy.deepcopy(self.cfg)
            old.pop('GLOBAL_ALLSKY_MAP')
            old['PRIVACY_MODE'] = private
            entry.data = old
            db.session.commit()
            data, _ = self._accuracy_form_data()
            data.update(GLOBAL_ALLSKY_MAP__ENABLE=True, GLOBAL_ALLSKY_MAP__IMAGE_URL=self.IMAGE_URL,
                        GLOBAL_ALLSKY_MAP__EQUIPMENT='Synthetic enclosure',
                        GLOBAL_ALLSKY_MAP__WEBSITE_URL='https://site.example.org/',
                        GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY='exact')
            response = self.client.post('/indi-allsky/ajax/config', json=data)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(IndiAllSkyConfigBase._base_config['GLOBAL_ALLSKY_MAP'], defaults)
            saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
            self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], 'legacy' if private else 'exact')
            self.assertEqual(saved['WEBSITE'], self.cfg['WEBSITE'])

    def test_legacy_website_url_load_save_and_explicit_empty_precedence(self):
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        old = copy.deepcopy(entry.data)
        old['GLOBAL_ALLSKY_MAP'].pop('WEBSITE_URL', None)
        old['WEBSITE']['PUBLIC_URL'] = 'https://legacy.example.org/'
        old['WEBSITE']['UNRELATED'] = 'preserve'
        entry.data = old
        db.session.commit()
        before = self.preview()
        data, _ = self._accuracy_form_data()
        self.assertEqual(data['GLOBAL_ALLSKY_MAP__WEBSITE_URL'], 'https://legacy.example.org/')
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.preview()['preview_token'], before['preview_token'])
        saved = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first().data
        self.assertEqual(saved['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'], 'https://legacy.example.org/')
        self.assertEqual(saved['WEBSITE'], old['WEBSITE'])
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__WEBSITE_URL'] = ''
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        self.assertEqual(self.preview()['metadata']['website_url'], '')



    def test_disable_survives_actual_gps_parent_location_writeback(self):
        self.preview()
        service = G.GlobalMapService()
        service._change(lambda state: state.update(registered=True, needs_review=False, last_success=0))
        stale = copy.deepcopy(self.cfg)
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        self.assertEqual(self.client.post('/indi-allsky/ajax/config', json=data).status_code, 200)
        self._write_stale_config(stale, relocation=True)
        self.assertTrue(service.state()['publication_suppressed'])
        self.assertIsNone(service.schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)



    def test_never_used_disabled_saves_create_no_map_state_or_identifier(self):
        for _ in range(2):
            data, _ = self._accuracy_form_data()
            data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
            with patch.object(G.GlobalMapService, 'suppress_publication',
                              side_effect=AssertionError('Unused feature must not write state')):
                response = self.client.post('/indi-allsky/ajax/config', json=data)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertIsNone(G.GlobalMapService().identifier())
            self.assertIsNone(db.session.get(IndiAllSkyDbStateTable, G.STATE_KEY))
            self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_never_used_disabled_save_ignores_and_preserves_corrupt_map_state(self):
        row = IndiAllSkyDbStateTable(key=G.STATE_KEY, value='{synthetic-corrupt-state')
        db.session.add(row)
        db.session.commit()
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        with patch.object(G.GlobalMapService, '_change',
                          side_effect=AssertionError('Unused feature must not depend on state')):
            response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(db.session.get(IndiAllSkyDbStateTable, G.STATE_KEY).value, '{synthetic-corrupt-state')
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_preview_only_installation_disable_still_establishes_durable_suppression(self):
        self.preview()
        identifier = G.GlobalMapService().identifier()
        data, _ = self._accuracy_form_data()
        data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        service = G.GlobalMapService()
        self.assertEqual(service.identifier(), identifier)
        self.assertTrue(service.state()['publication_suppressed'])
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_established_corrupt_state_disable_and_remove_fail_cleanly_without_overwrite(self):
        self.preview()
        service = G.GlobalMapService()
        identifier = service.identifier()
        for raw in ['{synthetic-corrupt-state', '[]', 'null', '"text"', '1', '']:
            row = db.session.get(IndiAllSkyDbStateTable, G.STATE_KEY)
            if row is None:
                row = IndiAllSkyDbStateTable(key=G.STATE_KEY, value=raw)
                db.session.add(row)
            else:
                row.value = raw
            db.session.commit()
            data, _ = self._accuracy_form_data()
            data['GLOBAL_ALLSKY_MAP__ENABLE'] = False
            count = IndiAllSkyDbConfigTable.query.count()
            with self.subTest(raw=raw, action='disable'):
                response = self.client.post('/indi-allsky/ajax/config', json=data)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()['form_global'], ['Stored map state is invalid; refusing to replace it'])
            with self.subTest(raw=raw, action='remove'):
                response = self.client.post(self.endpoint, json={'operation':'remove','confirm':True})
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()['error'], 'Stored map state is invalid; refusing to replace it')
            self.assertEqual(IndiAllSkyDbConfigTable.query.count(), count)
            self.assertEqual(service._read(G.STATE_KEY), raw)
            self.assertEqual(service.identifier(), identifier)
            self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)


if __name__=='__main__':unittest.main()
