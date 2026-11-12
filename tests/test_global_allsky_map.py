"""Real ORM/task integration with synthetic state and a network-denying test harness."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
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
        self.assertEqual(data['allsky_settings'], {}); self.assertEqual(data['website_settings'], {})
        self.assertEqual(data['camera'], 'Detected CCD'); self.assertEqual(data['allsky_version'], G.canonical_version(__version__))
        self.assertNotIn('NEVER-PUBLISH', json.dumps(data)); self.assertNotIn('OTHER-KEY', json.dumps(data))
        self.assertNotIn('imageBase64', data); self.assertFalse(data['force'])

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

    def test_stale_preview_does_not_send_changed_metadata(self):
        preview=self.s.preview();task_id=self.s.enqueue('register',preview['preview_token'])
        self.cfg['OWNER']='changed after preview'
        task=db.session.get(IndiAllSkyDbTaskQueueTable,task_id);task.setRunning()
        self.assertEqual(self.s.execute(task,**task.data['kwargs'])['status'],'STALE')
        self.assertEqual(self.calls,[]);self.assertFalse(self.s.state().get('registered'))

    def test_successful_task_is_never_posted_twice(self):
        task,result=self.run_job();self.assertTrue(result['ok'])
        self.assertEqual(self.s.execute(task,**task.data['kwargs'])['status'],'NOT_SENT')
        self.assertEqual(len(self.calls),1);self.assertTrue(self.s.state()['registered'])

    def test_ambiguous_timeout_pauses_automatic_requests(self):
        self.run_job();self.now+=301
        def timeout(req,**kwargs):self.calls.append((req,kwargs));raise error.URLError('timeout')
        self.s.opener=timeout
        _,result=self.run_job('update');self.assertFalse(result['ok'])
        self.assertTrue(self.s.state()['needs_review'])
        self.now+=G.REFRESH_SECONDS*2;self.assertIsNone(self.s.schedule());self.assertEqual(len(self.calls),2)

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
        self.assertEqual(self.s.state()['pending'],new_id)
        self.assertEqual(len(self.calls),1)
        new=db.session.get(IndiAllSkyDbTaskQueueTable,new_id);new.setRunning()
        self.assertTrue(self.s.execute(new,**new.data['kwargs'])['ok'])
        self.assertEqual(len(self.calls),2)


if __name__ == '__main__':
    unittest.main()
