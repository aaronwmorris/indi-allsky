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
        self.cfg.update(LOCATION_LATITUDE=35.5, LOCATION_LONGITUDE=-.12,
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
            'latitude': '35.5N', 'longitude': '0.12W',
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

    def test_url_combinations_preserve_supplied_values_without_host_matching(self):
        pairs = [('', ''), ('', 'https://images.example.org/latest.jpg'),
                 ('https://example.org:8443/archive/', 'https://example.org/latest.jpg'),
                 ('https://www.example.org/Archive/?view=sky',
                  'https://cdn.other.org:8443/Latest.JPG?raw=1&size=full')]
        for website, image in pairs:
            with self.subTest(website=website, image=image):
                G.validate_urls(website, image)
                self.cfg['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'] = website
                self.cfg['GLOBAL_ALLSKY_MAP']['IMAGE_URL'] = image
                data = self.s._payload(self.cfg, True)
                self.assertEqual(data['website_url'], website)
                self.assertEqual(data['image_url'], image)

    def test_url_validation_still_rejects_missing_image_and_unsafe_values(self):
        with self.assertRaises(G.MapError):
            G.validate_urls('https://example.org/', '')
        invalid = ['ftp://example.org/x', 'https://user:pass@example.org/x',
                   'https://127.0.0.1/x', 'https://10.0.0.1/x', 'https://[::1]/x',
                   ' https://example.org/x', 'https://example.org/x#frag',
                   'https://example.org:invalid/x', 'https://example.org/a b',
                   'https://example.org/\n', 'https://localhost/x', 'https://host.local/x']
        for value in invalid:
            with self.subTest(image=value), self.assertRaises(G.MapError):
                G.validate_urls('', value)
            with self.subTest(website=value), self.assertRaises(G.MapError):
                G.validate_urls(value, 'https://images.example.org/latest.jpg')

    @staticmethod
    def _degrees(text):
        return float(text[:-1]) * (-1 if text[-1] in 'SW' else 1)

    @staticmethod
    def _places(text):
        number = text[:-1]
        return len(number.split('.')[1]) if '.' in number else 0

    def test_accuracy_default_is_legacy_with_identical_payload_hash(self):
        self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=-12.654)
        before = self.s._payload(self.cfg, True)
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = 'legacy'
        self.assertEqual(self.s._payload(self.cfg), before)
        self.assertEqual(G.fingerprint(self.s._payload(self.cfg)), G.fingerprint(before))
        self.assertEqual(IndiAllSkyConfigBase._base_config['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'], 'legacy')
        self.assertEqual(G.publication_coordinates(35.123, -12.654), ('35.12N', '12.65W'))

    def test_accuracy_private_branch_preserves_all_legacy_private_outputs(self):
        modes = ['legacy', 'exact', '0.5km', '1km', '2km', '5km', 'invalid', '', None, []]
        for lat, lon in [(35.1, -.5), (-35.5, 0), (0, -0.0), (89.9, 179.9), (-90, -180)]:
            for mode in modes:
                with self.subTest(lat=lat, lon=lon, mode=mode):
                    self.assertEqual(G.publication_coordinates(lat, lon, True, mode),
                                     (G.coordinate(lat, True, True), G.coordinate(lon, False, True)))

    def test_accuracy_invalid_values_fail_closed_without_weakening_private_mode(self):
        for mode in ['', None, [], {}, 1, 'Exact', '10km']:
            with self.subTest(mode=mode), self.assertRaises(G.MapError):
                G.publication_coordinates(51, 0, False, mode)
        for lat, lon in [(None, 0), ('bad', 0), (91, 0), (0, -181), (float('nan'), 0), (0, float('inf'))]:
            for private in [False, True]:
                with self.subTest(lat=lat, lon=lon, private=private), self.assertRaises(G.MapError):
                    G.publication_coordinates(lat, lon, private, 'exact')

    def test_accuracy_exact_formats_stored_values_without_adding_precision(self):
        for lat, lon, expected in [(35.123, -12.654, ('35.123N', '12.654W')),
                (35.1, 12.6, ('35.1N', '12.6E')), ('35.100', '12.600', ('35.1N', '12.6E')),
                (10, 100, ('10N', '100E')), (0, -0., ('0N', '0E')),
                (1e-7, -1e-8, ('0.0000001N', '0.00000001W')),
                (-90, 180, ('90S', '180E')), (90, -180, ('90N', '180W'))]:
            with self.subTest(lat=lat, lon=lon):
                self.assertEqual(G.publication_coordinates(lat, lon, False, 'exact'), expected)

    def test_accuracy_grids_never_promote_axis_source_precision(self):
        modes = ['0.5km', '1km', '2km', '5km']
        for lat, lon, places in [(35.1, 12.6, (1, 1)), (35.123, 12.6, (3, 1)),
                                (35.1, 12.654, (1, 3)), (51, 0, (0, 0)),
                                (35.123234567, 12.654345678, (6, 6)), (-1e-7, 1e-8, (6, 6))]:
            for mode in modes:
                with self.subTest(lat=lat, lon=lon, mode=mode):
                    result = G.publication_coordinates(lat, lon, False, mode)
                    for value, limit in zip(result, places):
                        self.assertLessEqual(self._places(value), limit)
        for mode in modes:
            self.assertEqual(G.publication_coordinates(35.1, 12.6, False, mode), ('35.1N', '12.6E'))

    def test_accuracy_grids_are_finite_bounded_and_stable_at_edges(self):
        import random
        rng = random.Random(18)
        samples = [(0., 0.), (90., 180.), (-90., -180.), (89.999999, 179.999999),
                   (-89.999999, -179.999999), (0.000001, -0.000001)]
        samples += [(round(rng.uniform(-90, 90), 7), round(rng.uniform(-180, 180), 7)) for _ in range(300)]
        for mode in ['0.5km', '1km', '2km', '5km']:
            for lat, lon in samples:
                result = G.publication_coordinates(lat, lon, False, mode)
                actual = tuple(map(self._degrees, result))
                self.assertLessEqual(abs(actual[0]), 90)
                self.assertLessEqual(abs(actual[1]), 180)
                self.assertNotIn('e', ''.join(result))
                again = tuple(map(self._degrees, G.publication_coordinates(*actual, False, mode)))
                # Source-format rounding may shift a centre; re-gridding stays within
                # each output representation's quantum, not an assumed exact survey.
                for first, second, text in zip(actual, again, result):
                    self.assertLessEqual(abs(first - second), 10 ** -self._places(text) + 1e-9)
            self.assertEqual(G.publication_coordinates(90, 120, False, mode), ('90N', '0E'))
            self.assertEqual(G.publication_coordinates(-90, -120, False, mode), ('90S', '0E'))
            self.assertEqual(G.publication_coordinates(35.123234, 180, False, mode),
                             G.publication_coordinates(35.123234, -180, False, mode))

    def test_accuracy_grid_geographic_displacement_and_longitude_spacing(self):
        import math
        def distance(a, b):
            lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
            h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
            return 2 * 6371000 * math.asin(min(1, math.sqrt(h)))
        for mode, spacing in [('0.5km', 500), ('1km', 1000), ('2km', 2000), ('5km', 5000)]:
            for lat in [0.1234567, 35.1232345, -35.1232345, 80.1234567, 89.99999]:
                result = tuple(map(self._degrees, G.publication_coordinates(lat, 10.1234567, False, mode)))
                self.assertLess(distance((lat, 10.1234567), result), 2 * spacing + 1)
            for lat in [0.1234567, 35.1232345, 80.1234567]:
                nodes = []
                for index in range(300):
                    node = tuple(map(self._degrees, G.publication_coordinates(lat, 10.1234567 + index * .001, False, mode)))
                    if not nodes or nodes[-1] != node:
                        nodes.append(node)
                self.assertGreater(len(nodes), 1)
                for a, b in zip(nodes, nodes[1:]):
                    circumference = 2 * math.pi * 6371000 * math.cos(math.radians(a[0]))
                    # Integer rings use ceil(C/d): spacing is slightly below d.
                    # Allow that geometric bound and sub-metre display rounding.
                    self.assertLessEqual(distance(a, b), spacing + .5)
                    self.assertGreaterEqual(distance(a, b), spacing - spacing**2 / circumference - .5)

    def test_accuracy_longitude_grid_uses_only_the_quantised_latitude_row(self):
        for mode in ['0.5km', '1km', '2km', '5km']:
            with patch.object(G.math, 'cos', wraps=G.math.cos) as cos:
                first = G.publication_coordinates(35.1232341, 12.6543456, False, mode)
                second = G.publication_coordinates(35.1232342, 12.6543456, False, mode)
            self.assertEqual(first, second)
            self.assertEqual(cos.call_args_list[0], cos.call_args_list[1])

    def test_accuracy_grid_boundary_ties_and_decimal_source_rounding(self):
        import math
        rows = math.ceil(math.pi * 6371000 / 1000)
        # Select a representable half-cell boundary in the latitude-index domain.
        boundary = -90 + 10000.5 * 180 / rows
        low = self._degrees(G.publication_coordinates(boundary - 1e-8, 10.123456, False, '1km')[0])
        high = self._degrees(G.publication_coordinates(boundary + 1e-8, 10.123456, False, '1km')[0])
        self.assertGreater(high, low)
        self.assertEqual(G.publication_coordinates(boundary, 10.123456, False, '1km')[0],
                         G.publication_coordinates(boundary + 1e-8, 10.123456, False, '1km')[0])
        # Inject mathematical candidates at decimal half-ties to exercise the final
        # source cap independently of which grid nodes happen to be representable.
        from decimal import Decimal
        decimals = [Decimal('0.1'), Decimal('0.1'), Decimal('35.25'), Decimal(1), Decimal('.45'), Decimal(1)]
        with patch.object(G, 'Decimal', side_effect=decimals):
            self.assertEqual(G.publication_coordinates(0.1, 0.1, False, '1km'), ('35.2N', '0.4E'))

    def test_accuracy_uses_saved_source_and_never_promotes_precision_for_gps(self):
        self.cfg.update(LOCATION_LATITUDE=round(35.1001234, 3), LOCATION_LONGITUDE=round(12.6001234, 3))
        self.camera.latitude = 35.1001234
        self.camera.longitude = 12.6001234
        db.session.commit()
        for mode in ['exact', '0.5km', '1km', '2km', '5km']:
            self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = mode
            before = copy.deepcopy(self.cfg)
            manual = self.s._payload(self.cfg, True)
            self.cfg['GPS_ENABLE'] = True
            gps = self.s._payload(self.cfg)
            self.assertEqual(manual, gps)
            self.assertEqual((gps['latitude'], gps['longitude']), ('35.1N', '12.6E'))
            self.assertEqual(self.cfg['LOCATION_LATITUDE'], before['LOCATION_LATITUDE'])
            self.assertEqual(self.cfg['LOCATION_LONGITUDE'], before['LOCATION_LONGITUDE'])
            self.assertEqual(self.cfg['ALLSKYMAP'], before['ALLSKYMAP'])
            self.cfg['GPS_ENABLE'] = False

    def test_accuracy_effective_changes_use_existing_fingerprints_and_stale_review(self):
        self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654)
        self.run_job()
        self.now += 301
        preview = self.s.preview()
        task_id = self.s.enqueue('update', preview['preview_token'])
        self.s._change(lambda state: state.update(needs_review=True))
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = 'exact'
        with self.assertRaises(G.MapError):
            self.s.enqueue('update', preview['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.assertEqual(self.s.execute(task, **task.data['kwargs'])['status'], 'STALE')
        self.assertTrue(self.s.state()['needs_review'])
        self.assertTrue(self.s.status()['dirty'])
        self.assertIsNone(self.s.schedule())
        self.assertEqual(len(self.calls), 1)

    def test_accuracy_dirty_updates_coalesce_and_preview_matches_publication(self):
        self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654)
        self.run_job()
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = '1km'
        self.assertTrue(self.s.status()['dirty'])
        self.now += 301
        task_id = self.s.schedule()
        self.assertIsNotNone(task_id)
        self.assertIsNone(self.s.schedule())
        preview = self.s.preview()['metadata']
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        sent = json.loads(self.calls[-1][0].data)
        self.assertEqual((preview['latitude'], preview['longitude']), (sent['latitude'], sent['longitude']))
        self.assertNotIn('LOCATION_ACCURACY', sent)
        self.assertFalse(self.s.status()['dirty'])

    def test_accuracy_inactive_or_equivalent_choice_does_not_dirty_payload(self):
        self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654, PRIVACY_MODE=True)
        self.run_job()
        before = self.s._payload(self.cfg)
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = 'exact'
        self.assertEqual(self.s._payload(self.cfg), before)
        self.assertFalse(self.s.status()['dirty'])
        self.now += G.REFRESH_SECONDS - 1
        self.assertIsNone(self.s.schedule())
        self.cfg['PRIVACY_MODE'] = False
        self.assertTrue(self.s.status()['dirty'])
        self.cfg.update(LOCATION_LATITUDE=35.1, LOCATION_LONGITUDE=.5)
        first = self.s._payload(self.cfg)
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = '0.5km'
        self.assertEqual(self.s._payload(self.cfg), first)

    def test_accuracy_privacy_transitions_stale_queued_payload_and_preserve_review(self):
        for original in [False, True]:
            self.now += 301
            self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654, PRIVACY_MODE=original)
            self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = 'exact'
            self.run_job()
            self.now += 301
            preview = self.s.preview()
            task_id = self.s.enqueue('update', preview['preview_token'])
            self.s._change(lambda state: state.update(needs_review=True))
            calls = len(self.calls)
            self.cfg['PRIVACY_MODE'] = not original
            task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
            task.setRunning()
            self.assertEqual(self.s.execute(task, **task.data['kwargs'])['status'], 'STALE')
            self.assertEqual(task.state, TaskQueueState.FAILED)
            self.assertTrue(self.s.state()['needs_review'])
            self.assertEqual(len(self.calls), calls)
            self.assertIsNone(self.s.schedule())

    def test_accuracy_saved_gps_changes_dirty_only_the_emitted_coordinates(self):
        self.cfg.update(LOCATION_LATITUDE=35.123, LOCATION_LONGITUDE=12.654, GPS_ENABLE=True)
        self.run_job()
        before = self.s._payload(self.cfg)
        self.cfg['LOCATION_LATITUDE'] = 35.124
        self.assertEqual(self.s._payload(self.cfg), before)
        self.assertFalse(self.s.status()['dirty'])
        self.now += 301
        self.assertIsNone(self.s.schedule())
        self.cfg['GLOBAL_ALLSKY_MAP']['LOCATION_ACCURACY'] = 'exact'
        self.assertTrue(self.s.status()['dirty'])
        self.assertIsNotNone(self.s.schedule())
        self.assertIsNone(self.s.schedule())
        self.assertEqual(len(self.calls), 1)

    def test_coordinates_zero_sign_bounds_privacy(self):
        for val,lat,expected in [(35.5,True,'35.5N'),(-.12,False,'0.12W'),(0,True,'0N'),
                                (0,False,'0E'),(-90,True,'90S'),(180,False,'180E')]:
            self.assertEqual(G.coordinate(val,lat),expected)
        self.assertEqual(G.coordinate(35.6,True,True),'36N')
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


    def test_image_host_policy_with_independent_public_url_hosts(self):
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
        # Host differences, including terminal dots, are not a pairing restriction.
        G.validate_urls('https://example.org/', 'https://example.org./image')
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
        self.assertEqual(self.s.state(), dict(before, publication_suppressed=True))
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



    def test_website_url_legacy_fallback_and_explicit_new_key_preserve_fingerprint(self):
        website = 'https://website.example.org/archive/'
        self.cfg['WEBSITE']['PUBLIC_URL'] = website
        before = self.s._payload(self.cfg, True)
        self.cfg['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'] = website
        after = self.s._payload(self.cfg)
        self.assertEqual(before, after)
        self.assertEqual(G.fingerprint(before), G.fingerprint(after))
        self.cfg['GLOBAL_ALLSKY_MAP']['WEBSITE_URL'] = ''
        self.assertEqual(self.s._payload(self.cfg)['website_url'], '')
        self.assertNotIn('PUBLIC_URL', IndiAllSkyConfigBase._base_config['WEBSITE'])

    def test_numeric_ipv4_forms_and_terminal_dot_do_not_bypass_url_validation(self):
        for host in ['3232235777', '0x7f000001', '127.1', '127.0.1',
                     '0177.0.0.1', '0x7f.0.0.1', '2130706433',
                     '192.168.1.1.', '127.0.0.1.', '0X7F000001.']:
            for website in [False, True]:
                url = 'https://' + host + '/latest.jpg'
                with self.subTest(host=host, website=website), self.assertRaises(G.MapError):
                    G.validate_urls(url if website else '',
                                    'https://images.example.org/latest.jpg' if website else url)
        for host in ['8.8.8.8', '8.8.8.8.', '[2606:4700:4700::1111]',
                     '123.example.org', '0x7f.example.org', 'example.org']:
            G.validate_urls('', 'https://' + host + '/latest.jpg')

    def test_expected_preclaim_failure_preserves_prior_review_and_makes_no_attempt(self):
        for prior in [False, True]:
            self.camera.local = True
            db.session.commit()
            task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
            self.s._change(lambda state: state.update(needs_review=prior))
            self.camera.local = False
            db.session.commit()
            task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
            task.setRunning()
            result = self.s.execute(task, **task.data['kwargs'])
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(task.state, TaskQueueState.FAILED)
            self.assertEqual(self.s.state()['needs_review'], prior)
            self.assertNotIn('last_attempt', self.s.state())
            self.assertEqual(self.calls, [])

    def test_postclaim_diagnostic_failure_requires_review(self):
        task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        original = self.s._ensure
        def ensure(key, value):
            if key == G.RESPONSE_KEY:
                raise G.MapError('diagnostic store unavailable')
            return original(key, value)
        with patch.object(self.s, '_ensure', side_effect=ensure):
            result = self.s.execute(task, **task.data['kwargs'])
        self.assertFalse(result['ok'])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.s.state()['needs_review'])
        self.assertEqual(task.state, TaskQueueState.FAILED)

    def test_suppression_survives_stale_config_and_blocks_all_ordinary_paths(self):
        self.run_job()
        self.now += G.REFRESH_SECONDS + 1
        self.s.suppress_publication()
        # Simulate stale parent whole-config write-back setting ENABLE true again.
        self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE'] = True
        restarted = G.GlobalMapService(lambda: self.cfg, lambda: self.now, self.open)
        self.assertIsNone(restarted.schedule())
        self.assertIsNone(restarted.enqueue('update', automatic=True))
        preview = restarted.preview()
        for operation in ['update', 'force']:
            with self.subTest(operation=operation), self.assertRaises(G.MapError):
                restarted.enqueue(operation, preview['preview_token'])
        self.assertTrue(restarted.status()['publication_suppressed'])
        self.assertIn('explicitly Register', restarted.status()['publication_notice'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 1)

    def test_queued_publication_claim_rechecks_suppression_after_payload_construction(self):
        task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.s._change(lambda state: state.update(needs_review=True))
        original = self.s._payload
        def disable_after_read(config):
            data = original(config)
            self.s.suppress_publication()
            return data
        with patch.object(self.s, '_payload', side_effect=disable_after_read):
            result = self.s.execute(task, **task.data['kwargs'])
        self.assertEqual(result['status'], 'DISABLED')
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.assertTrue(self.s.state()['needs_review'])
        self.assertNotIn('last_attempt', self.s.state())
        self.assertEqual(self.calls, [])
        self.assertEqual(task.state, TaskQueueState.FAILED)

    def test_inflight_success_cannot_clear_new_suppression_or_resume_automation(self):
        task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        def sent_then_disable(data, opener=None, record=None):
            self.s.suppress_publication()
            return {'ok': True, 'status': 'UPDATED', 'message': ''}
        with patch.object(G, 'post', side_effect=sent_then_disable):
            self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        self.assertTrue(self.s.state()['registered'])
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.now += G.REFRESH_SECONDS + 1
        self.assertIsNone(self.s.schedule())

    def test_refused_remove_latches_suppression_before_inflight_request_finishes(self):
        task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        def remove_during_post(data, opener=None, record=None):
            with self.assertRaises(G.MapError):
                self.s.enqueue('remove')
            return {'ok': True, 'status': 'UPDATED', 'message': ''}
        with patch.object(G, 'post', side_effect=remove_during_post):
            self.assertTrue(self.s.execute(task, **task.data['kwargs'])['ok'])
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.assertTrue(self.cfg['GLOBAL_ALLSKY_MAP']['ENABLE'])
        self.now += G.REFRESH_SECONDS + 1
        self.assertIsNone(self.s.schedule())

    def test_remove_failure_remains_suppressed_despite_stale_enabled_config(self):
        self.run_job()
        task_id = self.s.enqueue('remove')
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        with patch.object(G, 'post', return_value={'ok': False, 'status': 'ALREADY_UPDATED', 'message': '5'}):
            self.s.execute(task, **task.data['kwargs'])
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.assertTrue(self.s.state()['registered'])
        self.now += G.REFRESH_SECONDS + 1
        self.assertIsNone(self.s.schedule())

    def test_only_valid_register_enqueue_clears_suppression_and_budget_failure_retains_it(self):
        self.run_job()
        self.s.suppress_publication()
        token = self.s.preview()['preview_token']
        with self.assertRaises(G.MapError):
            self.s.enqueue('register', 'wrong')
        with self.assertRaises(G.MapError):
            self.s.enqueue('register', token)  # Minimum interval has not elapsed.
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.now += 301
        self.s._change(lambda state: state.update(attempts=[{'force':False,'time':self.now}]*5))
        with self.assertRaises(G.MapError):
            self.s.enqueue('register', token)
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.now += G.QUOTA_SECONDS + 1
        self.s.enqueue('register', token)
        self.assertFalse(self.s.state()['publication_suppressed'])

    def test_register_enqueue_integrity_failure_rolls_back_suppression_release(self):
        self.s.preview()
        self.s.suppress_publication()
        with patch.object(db.session, 'flush', side_effect=RuntimeError('synthetic flush failure')):
            with self.assertRaises(RuntimeError):
                self.s.enqueue('register', self.s.preview()['preview_token'])
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)



    def test_neutral_synthetic_grid_expectations_from_independent_calculation(self):
        # R=6371000: row/ring calculations independently evaluated for 35.123/12.654.
        # These values are synthetic and unrelated to an installation.
        expected = {'0.5km': ('35.125N', '12.656E'), '1km': ('35.126N', '12.65E'),
                    '2km': ('35.126N', '12.655E'), '5km': ('35.11N', '12.641E')}
        for mode, pair in expected.items():
            with self.subTest(mode=mode):
                self.assertEqual(G.publication_coordinates(35.123, 12.654, False, mode), pair)

    def test_register_cas_contention_does_not_release_suppression_or_leave_job(self):
        self.s.preview()
        self.s.suppress_publication()
        with patch('sqlalchemy.orm.Query.update', return_value=0):
            with self.assertRaises(G.MapError):
                self.s.enqueue('register', self.s.preview()['preview_token'])
        self.assertTrue(self.s.state()['publication_suppressed'])
        self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 0)

    def test_suppressed_active_register_cannot_release_guard_but_expired_job_can_be_replaced(self):
        token = self.s.preview()['preview_token']
        first = self.s.enqueue('register', token)
        self.s.suppress_publication()
        with self.assertRaises(G.MapError):
            self.s.enqueue('register', token)
        self.assertTrue(self.s.state()['publication_suppressed'])
        old = db.session.get(IndiAllSkyDbTaskQueueTable, first)
        old.state = TaskQueueState.EXPIRED
        db.session.commit()
        second = self.s.enqueue('register', token)
        self.assertNotEqual(first, second)
        self.assertFalse(self.s.state()['publication_suppressed'])
        old.setRunning()
        self.assertEqual(self.s.execute(old, **old.data['kwargs'])['status'], 'NOT_SENT')
        self.assertEqual(self.s.state()['pending'], second)
        self.assertEqual(self.calls, [])



    def test_suppressed_duplicate_attempt_retains_pending_claim_and_review_evidence(self):
        task_id = self.s.enqueue('register', self.s.preview()['preview_token'])
        task = db.session.get(IndiAllSkyDbTaskQueueTable, task_id)
        task.setRunning()
        self.s._change(lambda state: state.update(attempted_task=task_id, last_attempt=self.now))
        self.s.suppress_publication()
        before = self.s.state()
        result = self.s.execute(task, **task.data['kwargs'])
        self.assertEqual(result['status'], 'NOT_SENT')
        self.assertEqual(self.s.state(), before)
        self.assertEqual(self.s.state()['pending'], task_id)
        self.assertTrue(self.s.status()['needs_review'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
