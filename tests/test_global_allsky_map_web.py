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
        self.assertIn(b'Global Allsky Map',r.data)
        self.assertIn(b'GLOBAL_ALLSKY_MAP__IMAGE_URL',r.data)
        self.assertIn(b'WEBSITE__PUBLIC_URL',r.data)
        self.assertEqual(self.client.get(self.endpoint).status_code,200)
        self.assertIsNone(G.GlobalMapService().identifier())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0)

    def test_real_form_save_is_not_registration(self):
        captured=[]
        def receive(sender,template,context,**kw):
            if 'form_config' in context:captured.append(context['form_config'])
        with template_rendered.connected_to(receive,APP):r=self.client.get('/indi-allsky/config')
        data=copy.deepcopy(captured[-1].data)
        data.update(GLOBAL_ALLSKY_MAP__ENABLE=True,GLOBAL_ALLSKY_MAP__IMAGE_URL=self.IMAGE_URL,
                    GLOBAL_ALLSKY_MAP__EQUIPMENT='Synthetic heater',WEBSITE__PUBLIC_URL='https://website.other.example/archive/',
                    RELOAD_ON_SAVE=False,CONFIG_NOTE='map test save')
        r=self.client.post('/indi-allsky/ajax/config',json=data)
        self.assertEqual(r.status_code,200,r.get_json())
        latest=IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        self.assertEqual(latest.data['GLOBAL_ALLSKY_MAP']['IMAGE_URL'],self.IMAGE_URL)
        self.assertEqual(latest.data['GLOBAL_ALLSKY_MAP']['EQUIPMENT'],'Synthetic heater')
        self.assertEqual(latest.data['WEBSITE']['PUBLIC_URL'], 'https://website.other.example/archive/')
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

    def test_different_domain_preview_and_worker_preserve_both_urls(self):
        website = 'https://website.other.example:8443/Archive/?view=sky'
        image = 'https://images.example.org/Latest.JPG?raw=1'
        entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        cfg = copy.deepcopy(entry.data)
        cfg['WEBSITE']['PUBLIC_URL'] = website
        cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'] = image
        entry.data = cfg
        db.session.commit()
        page = self.client.get('/indi-allsky/config')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'they may use different domains', page.data)
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
        self.assertIn(b'Existing rounding (2 decimal places)', page)
        self.assertIn(b'Exact configured location', page)
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
        cfg.update(PRIVACY_MODE=True, LOCATION_LATITUDE=51.741, LOCATION_LONGITUDE=.512)
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
        self.assertEqual((preview['latitude'], preview['longitude']), ('52N', '1E'))
        self.assertNotIn('51.741', str(preview))
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
        data.update(LOCATION_LATITUDE=51.741, LOCATION_LONGITUDE=.512,
                    GLOBAL_ALLSKY_MAP__LOCATION_ACCURACY='exact')
        response = self.client.post('/indi-allsky/ajax/config', json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        preview = self.preview()
        self.assertEqual((preview['metadata']['latitude'], preview['metadata']['longitude']), ('51.741N', '0.512E'))
        response = self.client.post(self.endpoint, json={'operation': 'register', 'preview_token': preview['preview_token']})
        self.assertEqual(response.status_code, 200, response.get_json())
        task, call = self.worker(response.get_json()['task_id'])
        self.assertEqual(task.state, TaskQueueState.SUCCESS)
        self.assertEqual(call.call_count, 1)
        self.assertEqual((self.sent['latitude'], self.sent['longitude']), ('51.741N', '0.512E'))
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
        self.assertIn(b'changes to the shared Owner, Location, coordinates, Lens or Privacy Mode', page.data)
        self.assertIn(b'are published automatically', page.data)

    def test_common_form_validator_rejects_proxy_only_when_enabled(self):
        from types import SimpleNamespace
        from wtforms.validators import ValidationError
        from indi_allsky.flask.forms import GLOBAL_ALLSKY_MAP_urls_validator
        form = SimpleNamespace(WEBSITE__PUBLIC_URL=SimpleNamespace(data=''),
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


if __name__=='__main__':unittest.main()
