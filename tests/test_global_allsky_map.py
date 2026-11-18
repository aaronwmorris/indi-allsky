"""Real ORM/task integration with synthetic state and a network-denying test harness."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

_TMP = tempfile.TemporaryDirectory(prefix='global-map-tests-')
_CONFIG = Path(_TMP.name) / 'flask.json'
_CONFIG.write_text(json.dumps({'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
    'SECRET_KEY': 'synthetic-only', 'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'MIGRATION_FOLDER': str(Path(_TMP.name) / 'migrations'), 'WTF_CSRF_ENABLED': False}))
os.environ['INDI_ALLSKY_FLASK_CONFIG'] = str(_CONFIG)
from indi_allsky.flask import create_app, db
from indi_allsky.flask.models import (IndiAllSkyDbCameraTable, IndiAllSkyDbStateTable,
    IndiAllSkyDbTaskQueueTable, TaskQueueState)
from indi_allsky.config import IndiAllSkyConfigBase
from indi_allsky import global_allsky_map as G
from indi_allsky.version import __version__

APP = create_app()


class Response(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'text/plain; charset=utf-8'}


class GlobalMapTest(unittest.TestCase):
    def setUp(self):
        self.context = APP.app_context(); self.context.push()
        db.create_all()
        self.cfg = copy.deepcopy(IndiAllSkyConfigBase._base_config)
        self.cfg['GLOBAL_ALLSKY_MAP'] = {'ENABLE': True, 'IMAGE_URL': 'https://images.example.org/latest.jpg', 'EQUIPMENT': ''}
        self.cfg.update(LOCATION_LATITUDE=51.5, LOCATION_LONGITUDE=-.12,
                        LOCATION_NAME='Synthetic site', OWNER='Synthetic owner')
        self.camera = IndiAllSkyDbCameraTable(name='Test CCD', local=True, data={'detected_name': 'Detected CCD'})
        db.session.add(self.camera); db.session.flush()
        db.session.add(IndiAllSkyDbStateTable(key='DB_CAMERA_ID', value=str(self.camera.id)))
        db.session.commit()
        self.now = 1800000000.; self.calls = []
        self.block = patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Real network forbidden'))
        self.block.start()
        self.comp = patch.object(G, 'computer_description', return_value='Generic PC, 8 GiB'); self.comp.start()
        self.s = G.GlobalMapService(lambda: self.cfg, lambda: self.now, self.open)

    def tearDown(self):
        self.comp.stop(); self.block.stop(); db.session.remove(); db.drop_all(); self.context.pop()

    def open(self, req, timeout):
        self.assertFalse(db.session().in_transaction(), 'No database transaction across network waits')
        self.calls.append((req, timeout))
        deleting = json.loads(req.data).get('website_url') == 'DELETE'
        return Response(b'RETURN DELETED\n' if deleting else b'RETURN UPDATED 1 5\n')

    def run_job(self, operation='register', service=None):
        service = service or self.s
        preview = service.preview()
        task_id = service.enqueue(operation, preview['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        result = service.execute(task, **task.data['kwargs'])
        return task, result

    def test_payload_is_allowlisted_and_contains_no_configuration(self):
        self.cfg['PRIVATE_TOKEN'] = 'NEVER-PUBLISH'; self.cfg['ALLSKYMAP']['API_KEY'] = 'OTHER-KEY'
        data = self.s._payload(self.cfg, create=True)
        self.assertEqual(set(data), {'force','machine_id','location','owner','latitude','longitude',
            'website_url','image_url','camera','lens','computer','equipmentinfo','allsky_version',
            'website_settings','allsky_settings'})
        self.assertEqual(data['allsky_settings'], {'equipmentinfo': ''}); self.assertEqual(data['website_settings'], {})
        self.assertEqual(data['camera'], 'Detected CCD'); self.assertEqual(data['allsky_version'], G.canonical_version(__version__))
        self.assertNotIn('NEVER-PUBLISH', json.dumps(data)); self.assertNotIn('OTHER-KEY', json.dumps(data))
        self.assertNotIn('imageBase64', data); self.assertFalse(data['force'])

    def test_equipment_is_duplicated_without_changing_other_payload_fields(self):
        equipment = 'Example heater; quotes " and Unicode ☁'
        self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT'] = equipment
        data = self.s._payload(self.cfg, create=True)
        self.assertEqual(data, {
            'force': False, 'machine_id': self.s.identifier(),
            'location': 'Synthetic site', 'owner': 'Synthetic owner',
            'latitude': '51.5N', 'longitude': '0.12W',
            'website_url': '', 'image_url': 'https://images.example.org/latest.jpg',
            'camera': 'Detected CCD', 'lens': self.cfg['LENS_NAME'],
            'computer': 'Generic PC, 8 GiB', 'equipmentinfo': equipment,
            'allsky_version': G.canonical_version(__version__), 'website_settings': {},
            'allsky_settings': {'equipmentinfo': equipment},
        })
        self.assertTrue(data['allsky_version'].startswith('indi_'))
        encoded = json.loads(json.dumps(data))
        self.assertEqual(encoded['equipmentinfo'], encoded['allsky_settings']['equipmentinfo'])

    def test_empty_or_unconfigured_equipment_is_empty_in_both_locations(self):
        for value in ('', None):
            with self.subTest(value=value):
                self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT'] = value
                data = self.s._payload(self.cfg, create=True)
                self.assertEqual(data['equipmentinfo'], '')
                self.assertEqual(data['allsky_settings'], {'equipmentinfo': ''})
        del self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT']
        data = self.s._payload(self.cfg)
        self.assertEqual(data['equipmentinfo'], '')
        self.assertEqual(data['allsky_settings'], {'equipmentinfo': ''})
        del self.cfg['GLOBAL_ALLSKY_MAP']
        data = self.s._payload(self.cfg)
        self.assertEqual(data['equipmentinfo'], '')
        self.assertEqual(data['allsky_settings'], {'equipmentinfo': ''})

    def test_urls_image_only_and_same_domain_without_rewriting(self):
        G.validate_urls('', 'https://images.example.org/latest.jpg')
        G.validate_urls('https://example.org:8443/archive/', 'https://www.example.org/latest.jpg')
        for website,image in [('https://example.org/', ''),('https://example.org/','https://cdn.other.org/latest.jpg'),
              ('','ftp://example.org/x'),('','https://user:pass@example.org/x'),('','https://127.0.0.1/x'),
              ('',' https://example.org/x'),('','https://example.org/x#frag')]:
            with self.subTest(website=website,image=image), self.assertRaises(G.MapError):G.validate_urls(website,image)
        data=self.s._payload(self.cfg,True)
        self.assertEqual(data['image_url'],self.cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'])
        self.assertEqual(data['website_url'],'')

    def test_coordinates_zero_sign_bounds_privacy(self):
        for val,lat,expected in [(51.5,True,'51.5N'),(-.12,False,'0.12W'),(0,True,'0N'),
                                (0,False,'0E'),(-90,True,'90S'),(180,False,'180E')]:
            self.assertEqual(G.coordinate(val,lat),expected)
        self.assertEqual(G.coordinate(51.6,True,True),'52N')
        for val,lat in [(91,True),(181,False),(float('nan'),True),(float('inf'),False),('bad',True)]:
            with self.assertRaises(G.MapError):G.coordinate(val,lat)

    def test_identifier_is_random_persistent_and_never_reads_machine_id(self):
        with patch('pathlib.Path.read_text',side_effect=AssertionError('Host file must not be read')):
            first=self.s.identifier(True)
            self.assertRegex(first,r'^[0-9a-f]{32}$')
            self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=False
            self.assertEqual(G.GlobalMapService(lambda:self.cfg).identifier(True),first)
            self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=True
            self.assertEqual(self.s.identifier(True),first)
        self.assertEqual(IndiAllSkyDbStateTable.query.filter_by(key=G.ID_KEY).count(),1)

    def test_invalid_existing_identifier_is_not_regenerated(self):
        db.session.add(IndiAllSkyDbStateTable(key=G.ID_KEY,value='invalid'));db.session.commit()
        with self.assertRaises(G.MapError):self.s.identifier(True)
        self.assertEqual(self.s._read(G.ID_KEY),'invalid')

    def test_optional_text_and_version_are_truthful(self):
        self.cfg.update(OWNER='',LOCATION_NAME='',LENS_NAME='')
        self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT']='quotes " and apostrophe \' / Unicode ☁'
        data=self.s._payload(self.cfg,True)
        self.assertEqual(data['owner'],'');self.assertEqual(data['location'],'')
        self.assertEqual(json.loads(json.dumps(data))['equipmentinfo'],self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT'])
        with patch.object(G,'__version__','indi_v2026.11.01+development.test'):
            self.assertEqual(self.s._payload(self.cfg)['allsky_version'],'indi_v2026.11.01')

    def test_remote_or_missing_camera_does_not_publish(self):
        self.camera.local=False;db.session.commit()
        with self.assertRaises(G.MapError):self.s.preview()
        self.assertEqual(self.calls,[])

    def test_disabled_and_unregistered_startup_make_no_requests(self):
        self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=False
        self.assertIsNone(self.s.schedule())
        with self.assertRaises(G.MapError):self.s.enqueue('force','anything')
        self.assertEqual(self.s.state(),{});self.assertIsNone(self.s.identifier())
        self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=True
        for _ in range(3):self.assertIsNone(G.GlobalMapService(lambda:self.cfg).schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),0);self.assertEqual(self.calls,[])

    def test_preview_and_explicit_registration_require_review(self):
        preview=self.s.preview();self.assertNotIn(self.s.identifier(),json.dumps(preview))
        self.assertEqual(self.calls,[])
        with self.assertRaises(G.MapError):self.s.enqueue('register')
        with self.assertRaises(G.MapError):self.s.enqueue('register','incorrect')
        task,result=self.run_job()
        self.assertTrue(result['ok']);self.assertEqual(task.state,TaskQueueState.SUCCESS)
        req,timeout=self.calls[0];data=json.loads(req.data)
        self.assertEqual(req.full_url,G.ENDPOINT);self.assertEqual(req.get_method(),'POST')
        self.assertEqual(timeout,G.TIMEOUT);self.assertEqual(req.get_header('Content-type'),'application/json')
        self.assertFalse(data['force']);self.assertTrue(self.s.state()['registered'])

    def test_pending_tasks_and_restarts_do_not_duplicate(self):
        preview=self.s.preview();first=self.s.enqueue('register',preview['preview_token'])
        for _ in range(3):
            s=G.GlobalMapService(lambda:self.cfg,lambda:self.now,self.open)
            self.assertEqual(s.enqueue('register',preview['preview_token']),first)
            self.assertIsNone(s.schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),1);self.assertEqual(self.calls,[])

    def test_periodic_refresh_is_persistent_and_every_48_hours(self):
        self.run_job();self.assertIsNone(self.s.schedule())
        self.now+=G.REFRESH_SECONDS-1;self.assertIsNone(self.s.schedule())
        self.now+=2;s=G.GlobalMapService(lambda:self.cfg,lambda:self.now,self.open)
        task_id=s.schedule();self.assertIsNotNone(task_id)
        self.assertIsNone(s.schedule());self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),2)
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);self.assertEqual(task.data['kwargs']['operation'],'update')
        task.setRunning();self.assertTrue(s.execute(task,**task.data['kwargs'])['ok'])
        self.assertFalse(json.loads(self.calls[-1][0].data)['force']);self.assertIsNone(s.schedule())

    def test_metadata_changes_are_dirty_and_coalesce(self):
        self.run_job();self.cfg['GLOBAL_ALLSKY_MAP']['EQUIPMENT']='new lens heater'
        self.assertTrue(self.s.status()['dirty']);self.assertIsNone(self.s.schedule())
        self.now+=301;task_id=self.s.schedule();self.assertIsNotNone(task_id)
        self.assertIsNone(self.s.schedule());self.assertEqual(len(self.calls),1)

    def test_queued_update_rechecks_enable(self):
        preview=self.s.preview();task_id=self.s.enqueue('register',preview['preview_token'])
        self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=False
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);task.setRunning()
        self.assertEqual(self.s.execute(task,**task.data['kwargs'])['status'],'DISABLED')
        self.assertEqual(self.calls,[]);self.assertIsNone(self.s.schedule())
        self.assertFalse(self.s.state().get('needs_review', False))

    def test_stale_preview_does_not_send_changed_metadata(self):
        preview=self.s.preview();task_id=self.s.enqueue('register',preview['preview_token'])
        self.cfg['OWNER']='changed after preview'
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);task.setRunning()
        self.assertEqual(self.s.execute(task,**task.data['kwargs'])['status'],'STALE')
        self.assertEqual(self.calls,[]);self.assertFalse(self.s.state().get('registered'))
        self.assertFalse(self.s.state().get('needs_review', False))

    def test_successful_task_is_never_posted_twice(self):
        task,result=self.run_job();self.assertTrue(result['ok'])
        self.assertEqual(self.s.execute(task,**task.data['kwargs'])['status'],'NOT_SENT')
        self.assertEqual(len(self.calls),1);self.assertTrue(self.s.state()['registered'])
        self.assertEqual(task.state,TaskQueueState.SUCCESS)

    def test_ambiguous_timeout_pauses_automatic_requests(self):
        self.run_job();self.now+=301
        def timeout(req,**kwargs):self.calls.append((req,kwargs));raise error.URLError('timeout')
        self.s.opener=timeout
        _,result=self.run_job('update');self.assertFalse(result['ok'])
        self.assertTrue(self.s.state()['needs_review'])
        self.now+=G.REFRESH_SECONDS*2;self.assertIsNone(self.s.schedule());self.assertEqual(len(self.calls),2)

    def _assert_unsent_outcome_preserves_review(self, outcome):
        self.run_job()
        self.now += 301
        def timeout(req, **kwargs):
            self.calls.append((req, kwargs))
            raise error.URLError('synthetic ambiguous timeout')
        self.s.opener = timeout
        previous, result = self.run_job('update')
        self.assertFalse(result['ok'])
        self.assertTrue(self.s.state()['needs_review'])
        self.now += 301
        preview = self.s.preview()
        task_id = self.s.enqueue('update', preview['preview_token'])
        before = self.s.state()
        if outcome == 'STALE':
            self.cfg['OWNER'] = 'Changed after manual update was queued'
        else:
            self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE'] = False
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        result = self.s.execute(task, **task.data['kwargs'])
        self.assertEqual(result['status'], outcome)
        self.assertEqual(task.state, TaskQueueState.FAILED)
        after = self.s.state()
        self.assertTrue(after['needs_review'])
        self.assertNotIn('pending', after)
        for key in ('registered', 'last_success', 'last_attempt', 'attempts', 'attempted_task', 'payload_hash'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after['attempted_task'], previous.id)
        self.assertTrue(after['last_status'].startswith(outcome + ':'))
        self.assertEqual(len(self.calls), 2)  # Registration and the ambiguous update only.
        # Re-enable and wait until a refresh is due: review, not Disable/cooldown, blocks it.
        self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE'] = True
        self.now += G.REFRESH_SECONDS + 1
        self.assertIsNone(self.s.schedule())
        self.assertTrue(self.s.state()['needs_review'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 3)

    def test_stale_manual_update_preserves_review_after_ambiguous_request(self):
        self._assert_unsent_outcome_preserves_review('STALE')

    def test_disabled_manual_update_preserves_review_after_ambiguous_request(self):
        self._assert_unsent_outcome_preserves_review('DISABLED')

    def test_five_attempt_budget_and_explicit_force(self):
        for i in range(5):
            self.run_job('register' if i==0 else 'update');self.now+=61
        preview=self.s.preview()
        with self.assertRaises(G.MapError):self.s.enqueue('update',preview['preview_token'])
        task,result=self.run_job('force');self.assertTrue(result['ok'])
        self.assertTrue(json.loads(self.calls[-1][0].data)['force']);self.assertEqual(len(self.calls),6)
        with self.assertRaises(G.MapError):self.s.enqueue('update',preview['preview_token'])

    def test_remove_sends_only_delete_fields_and_keeps_identity(self):
        self.run_job();identifier=self.s.identifier();self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE']=False
        task_id=self.s.enqueue('remove');task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);task.setRunning()
        result=self.s.execute(task,**task.data['kwargs']);self.assertTrue(result['ok'])
        self.assertEqual(json.loads(self.calls[-1][0].data),{'machine_id':identifier,'website_url':'DELETE'})
        self.assertFalse(self.s.state()['registered']);self.assertEqual(self.s.identifier(),identifier)
        self.assertIsNone(self.s.schedule())
        with self.assertRaises(G.MapError):self.s.enqueue('remove')

    def test_return_statuses_and_malformed_responses(self):
        for text,status,ok in [('RETURN INSERTED','INSERTED',True),('RETURN UPDATED 2 5','UPDATED',True),
            ('RETURN ERROR rejected','ERROR',False),('RETURN ALREADY_UPDATED 5','ALREADY_UPDATED',False)]:
            result=G.parse_response(text);self.assertEqual((result['status'],result['ok']),(status,ok))
        self.assertTrue(G.parse_response('RETURN DELETED',True)['ok'])
        self.assertEqual(G.parse_response('RETURN MESSAGE hello\nRETURN UPDATED 1 5')['messages'],['hello'])
        for text in ['', '{}', 'RETURN MESSAGE only', 'RETURN WHAT', 'RETURN UPDATED x 5',
                     'RETURN INSERTED\nRETURN UPDATED 1 5', 'RETURN DELETED']:
            with self.subTest(text=text),self.assertRaises(G.MapError):G.parse_response(text)

    def test_http_error_timeout_oversized_and_message_only_are_not_success(self):
        data=self.s._payload(self.cfg,True)
        cases=[error.HTTPError(G.ENDPOINT,503,'unavailable',{},None),TimeoutError(),error.URLError('offline')]
        for exc in cases:
            calls=[]
            def opener(*args,**kwargs):calls.append(1);raise exc
            with self.assertRaises(G.MapError):G.post(data,opener)
            self.assertEqual(len(calls),1)
        for body in [b'x'*(G.MAX_RESPONSE+1),b'RETURN MESSAGE only']:
            with self.assertRaises(G.MapError):G.post(data,lambda *a,**k:Response(body))
        self.assertEqual(self.calls,[])

    def test_server_quota_does_not_record_success_or_retry_immediately(self):
        self.run_job();last_success=self.s.state()['last_success'];self.now+=301
        self.s.opener=lambda *a,**k:Response(b'RETURN ALREADY_UPDATED 5')
        _,result=self.run_job('update');self.assertFalse(result['ok'])
        self.assertEqual(self.s.state()['last_success'],last_success)
        self.assertEqual(self.s.status()['quota']['maximum'],5);self.assertIsNone(self.s.schedule())

    def test_interrupted_attempt_surfaces_review_without_republication(self):
        preview=self.s.preview()
        task_id=self.s.enqueue('register',preview['preview_token'])
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id)
        self.s._change(lambda state:state.update(registered=True,attempted_task=task_id,last_status='Sending register'))
        task.state=TaskQueueState.EXPIRED;db.session.commit()
        self.assertTrue(self.s.status()['needs_review'])
        self.now+=3*G.REFRESH_SECONDS
        self.assertIsNone(self.s.schedule())
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(),1)
        self.assertFalse(self.calls)

    def test_parent_restart_replaces_only_never_attempted_registered_refresh(self):
        self.run_job()
        self.now+=G.REFRESH_SECONDS
        old_id=self.s.schedule()
        old=db.session.get(IndiAllSkyDbTaskQueueTable,old_id)
        old.state=TaskQueueState.EXPIRED;db.session.commit()
        new_id=self.s.schedule()
        self.assertIsNotNone(new_id);self.assertNotEqual(old_id,new_id)
        self.assertIsNone(self.s.schedule())
        old.setRunning()
        result=self.s.execute(old,**old.data['kwargs'])
        self.assertEqual(result['status'],'NOT_SENT')
        self.assertEqual(old.state,TaskQueueState.FAILED)
        self.assertEqual(self.s.state()['pending'],new_id)
        self.assertEqual(len(self.calls),1)
        new=db.session.get(IndiAllSkyDbTaskQueueTable,new_id);new.setRunning()
        self.assertTrue(self.s.execute(new,**new.data['kwargs'])['ok'])
        self.assertEqual(len(self.calls),2)


    def test_image_host_policy_and_unchanged_domain_pairing(self):
        forbidden = ['allsky-map.com', 'www.allsky-map.com', 'nested.cdn.allsky-map.com',
                     'ALLSKY-MAP.COM', 'allsky-map.com.', 'cdn.Allsky-Map.Com..', 'allsky-map.com:443']
        for host in forbidden:
            with self.subTest(host=host), self.assertRaises(G.MapError):
                G.validate_urls('', 'https://' + host + '/api/cameras/example/image')
        for host in ['notallsky-map.com', 'fooallsky-map.com', 'allsky-map.com.example.org']:
            G.validate_urls('', 'https://' + host + '/latest.jpg')
        # Only the image host is forbidden; do not couple this to ALLSKYMAP.API_URL.
        G.validate_urls('https://allsky-map.com.example.org/', 'https://allsky-map.com.example.org/image')
        for host in ['localhost.', 'LOCALHOST..', 'camera.local.', 'CAMERA.LOCAL..']:
            with self.subTest(host=host), self.assertRaises(G.MapError):
                G.validate_urls('', 'https://' + host + '/image')
        G.validate_urls('https://example.org/', 'https://www.example.org/image')
        G.validate_urls('https://example.org./', 'https://example.org./image')
        # M10 remains unchanged: terminal-dot policy checks do not alter pair matching.
        with self.assertRaises(G.MapError):
            G.validate_urls('https://example.org/', 'https://example.org./image')
        with self.assertRaises(G.MapError):
            G.validate_urls('https://example.org/', 'https://cdn.example.org/image')

    def test_forbidden_image_is_checked_again_before_queued_post(self):
        preview = self.s.preview()
        task_id = self.s.enqueue('register', preview['preview_token'])
        self.cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'] = 'https://ALLSKY-MAP.COM./image'
        with self.assertRaises(G.MapError):
            self.s.preview()
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        result = self.s.execute(task, **task.data['kwargs'])
        self.assertFalse(result['ok'])
        self.assertEqual(task.state, TaskQueueState.FAILED)
        self.assertEqual(self.calls, [])
        self.assertNotIn('attempted_task', self.s.state())

    def test_remove_exempts_full_budget_without_consuming_or_evicting_attempts(self):
        self.s.preview()
        attempts = [{'time': self.now - 10, 'force': False} for _ in range(5)]
        self.s._change(lambda state: state.update(attempts=attempts, registered=True))
        for _ in range(3):
            task_id = self.s.enqueue('remove')
            task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
            task.setRunning()
            # Server failure leaves withdrawal available and does not invent success.
            self.s.opener = lambda *a, **k: Response(b'RETURN ERROR refused')
            result = self.s.execute(task, **task.data['kwargs'])
            self.assertFalse(result['ok'])
            self.assertTrue(self.s.state()['registered'])
            self.assertEqual(self.s.state()['attempts'], attempts)
            self.assertEqual(self.s.state()['attempted_task'], task_id)
        self.s.opener = self.open
        task_id = self.s.enqueue('remove')
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        self.assertEqual(self.s.state()['attempts'], attempts)
        self.assertFalse(self.s.state()['registered'])
        self.assertEqual(json.loads(self.calls[-1][0].data)['website_url'], 'DELETE')
        with self.assertRaises(G.MapError):
            self.s.enqueue('update', self.s.preview()['preview_token'])

    def test_remove_with_identifier_and_no_history_is_still_available(self):
        identifier = self.s.preview()['metadata']['machine_id']
        self.assertEqual(identifier, '(installation identifier hidden)')
        task_id = self.s.enqueue('remove')
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        self.assertEqual(self.s.state()['attempts'], [])

    def test_remove_does_not_release_an_attempted_active_publication(self):
        preview = self.s.preview()
        task_id = self.s.enqueue('register', preview['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.s._change(lambda state: state.update(attempted_task=task_id, last_attempt=self.now))
        before = self.s.state()
        with self.assertRaises(G.MapError):
            self.s.enqueue('remove')
        self.assertEqual(self.s.state(), before)
        self.assertEqual(task.state, TaskQueueState.RUNNING)
        self.assertEqual(self.calls, [])

    def test_remove_ambiguous_or_quota_response_never_claims_deletion(self):
        self.s.preview()
        self.s._change(lambda state: state.update(registered=True))
        for body in [b'unknown', b'RETURN ALREADY_UPDATED 5']:
            with self.subTest(body=body):
                self.s.opener = lambda *a, **k: Response(body)
                task_id = self.s.enqueue('remove')
                task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
                task.setRunning()
                self.assertFalse(self.s.execute(task, **task.data['kwargs'])['ok'])
                self.assertTrue(self.s.state()['registered'])
                self.assertFalse(self.s.state()['attempts'])

    def test_manual_pending_intent_is_not_silently_changed(self):
        self.run_job()
        self.now += G.REFRESH_SECONDS
        task_id = self.s.schedule()
        token = self.s.preview()['preview_token']
        self.assertEqual(self.s.enqueue('update', token), task_id)
        with self.assertRaisesRegex(G.MapError, 'different map request'):
            self.s.enqueue('force', token)
        self.cfg['OWNER'] = 'Changed owner'
        with self.assertRaisesRegex(G.MapError, 'different map request'):
            self.s.enqueue('update', self.s.preview()['preview_token'])
        self.assertIsNone(self.s.schedule())
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        self.assertEqual(task.data['kwargs']['operation'], 'update')
        self.assertEqual(len(self.calls), 1)

    def test_malformed_response_evidence_is_read_only_but_core_state_fails_closed(self):
        self.s.preview()
        for value in ['bad json', '[]', 'null', '"text"']:
            self.s._ensure(G.RESPONSE_KEY, value)
            row = IndiAllSkyDbStateTable.query.filter_by(key=G.RESPONSE_KEY).one()
            row.value = value
            db.session.commit()
            with self.subTest(value=value):
                status = self.s.status()
                self.assertEqual(status['response_evidence_error'], 'Stored response evidence is invalid')
                self.assertNotIn('response_evidence', status)
                self.assertEqual(self.s._read(G.RESPONSE_KEY), value)
                self.assertEqual(self.s.state(), {})
        self.s._ensure(G.STATE_KEY, '{broken')
        with self.assertRaises(G.MapError):
            self.s.status()

    def test_unexpected_preclaim_failure_preserves_earlier_review(self):
        for existing_review in [False, True]:
            with self.subTest(existing_review=existing_review):
                token = self.s.preview()['preview_token']
                task_id = self.s.enqueue('register', token)
                task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
                task.setRunning()
                self.s._change(lambda state: state.update(needs_review=existing_review))
                with patch.object(self.s, '_payload', side_effect=RuntimeError('private exception')):
                    result = self.s.execute(task, **task.data['kwargs'])
                self.assertEqual(task.state, TaskQueueState.FAILED)
                self.assertEqual(self.s.state()['needs_review'], existing_review)
                self.assertNotIn('attempted_task', self.s.state())
                self.assertNotIn('private exception', result['message'])
        self.assertEqual(self.calls, [])

    def test_unexpected_after_claim_and_evidence_failure_are_not_retried(self):
        for phase in ['post', 'evidence']:
            self.now += 301
            token = self.s.preview()['preview_token']
            task_id = self.s.enqueue('register', token)
            task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
            task.setRunning()
            if phase == 'post':
                def fail(*args, **kwargs):
                    raise RuntimeError('private ' + self.s.identifier())
                context = patch.object(G, 'post', side_effect=fail)
            else:
                original = self.s._ensure
                def fail(key, value):
                    if key == G.RESPONSE_KEY:
                        raise RuntimeError('evidence persistence unavailable')
                    return original(key, value)
                context = patch.object(self.s, '_ensure', side_effect=fail)
            with context:
                result = self.s.execute(task, **task.data['kwargs'])
            self.assertFalse(result['ok'])
            self.assertEqual(task.state, TaskQueueState.FAILED)
            self.assertTrue(self.s.state()['needs_review'])
            self.assertEqual(self.s.state()['attempted_task'], task_id)
            self.assertIsNone(self.s.schedule())
            self.assertEqual(self.s.execute(task, **task.data['kwargs'])['status'], 'NOT_SENT')
        self.assertEqual(len(self.calls), 1)

    def test_superseded_finish_does_not_change_new_owner_or_status(self):
        token = self.s.preview()['preview_token']
        task_id = self.s.enqueue('register', token)
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        replacement = {'pending': task_id + 100, 'registered': True,
                       'last_status': 'Replacement result', 'needs_review': True,
                       'quota': {'maximum': 99}, 'attempted_task': task_id + 100}
        def late_result(*args, **kwargs):
            self.s._change(lambda state: (state.clear(), state.update(replacement)))
            return {'ok': True, 'status': 'UPDATED', 'message': ''}
        with patch.object(G, 'post', side_effect=late_result):
            self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        self.assertEqual(self.s.state(), replacement)
        self.assertEqual(task.state, TaskQueueState.SUCCESS)

    def test_claim_commit_error_retains_durable_claim_and_requires_review(self):
        token = self.s.preview()['preview_token']
        task_id = self.s.enqueue('register', token)
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        original = self.s._change
        def committed_then_error(change):
            result = original(change)
            if change.__name__ == 'claim':
                raise RuntimeError('claim commit acknowledgement failed')
            return result
        with patch.object(self.s, '_change', side_effect=committed_then_error):
            result = self.s.execute(task, **task.data['kwargs'])
        self.assertFalse(result['ok'])
        self.assertEqual(task.state, TaskQueueState.FAILED)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.s.state()['needs_review'])
        self.assertEqual(self.s.state()['attempted_task'], task_id)
        self.assertEqual(self.s.execute(task, **task.data['kwargs'])['status'], 'NOT_SENT')

    def test_not_sent_preserves_all_existing_terminal_task_states(self):
        task, _ = self.run_job()
        for terminal in (TaskQueueState.SUCCESS, TaskQueueState.FAILED, TaskQueueState.EXPIRED):
            task.state = terminal
            db.session.commit()
            before = self.s.state()
            self.assertEqual(self.s.execute(task, **task.data['kwargs'])['status'], 'NOT_SENT')
            self.assertEqual(task.state, terminal)
            self.assertEqual(self.s.state(), before)
        self.assertEqual(len(self.calls), 1)

    def test_periodic_feature_failure_does_not_skip_core_housekeeping(self):
        from indi_allsky.allsky import IndiAllSky
        from unittest.mock import Mock
        worker = IndiAllSky.__new__(IndiAllSky)
        worker.periodic_tasks_time = 0
        worker.periodic_tasks_offset = 300
        worker.cleanup_tasks_time = 0
        worker.cleanup_tasks_offset = 300
        for name in ['aurora', 'smoke', 'sat_data', 'backup']:
            setattr(worker, name + '_tasks_time', self.now + 100)
        worker.config = {}
        worker._flushOldTasks = Mock()
        worker._systemHealthCheck = Mock()
        def poison_session():
            db.session.add(IndiAllSkyDbStateTable(key='DB_CAMERA_ID', value='duplicate'))
            db.session.flush()  # Leaves the session requiring rollback.
        for failure in [RuntimeError('private'), G.MapError('Expected scheduling error'), poison_session]:
            worker.periodic_tasks_time = 0
            worker.cleanup_tasks_time = 0
            worker._flushOldTasks.reset_mock()
            worker._systemHealthCheck.reset_mock()
            worker._flushOldTasks.side_effect = lambda: IndiAllSkyDbCameraTable.query.count()
            with patch.object(G.GlobalMapService, 'schedule', side_effect=failure), \
                    patch('indi_allsky.allsky.time.time', return_value=self.now), \
                    patch.object(db.session, 'rollback', wraps=db.session.rollback) as rollback:
                worker._periodic_tasks()
            rollback.assert_called_once()
            worker._flushOldTasks.assert_called_once()
            worker._systemHealthCheck.assert_called_once()


if __name__ == '__main__':
    unittest.main()
