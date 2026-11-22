import json
from pathlib import Path
import unittest
from unittest.mock import patch

from indi_allsky.gpsd_client import parse_gpsd_messages, query_gpsd


class _FakeSocket:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.sent = []
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _bufsize):
        if self._chunks:
            return self._chunks.pop(0)
        return b''


class TestGpsdClient(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]

    def test_parse_poll_payload(self):
        messages = [
            {'class': 'VERSION', 'release': '3.25'},
            {'class': 'DEVICES', 'devices': [{'path': '/dev/ttyAMA0', 'driver': 'NMEA0183', 'bps': 9600}]},
            {
                'class': 'POLL',
                'tpv': [{
                    'mode': 3,
                    'time': '2026-11-22T09:00:00.000Z',
                    'lat': -34.9285,
                    'lon': 138.6007,
                    'altMSL': 52.4,
                    'epx': 2.1,
                    'epy': 2.5,
                    'epv': 4.0,
                }],
                'sky': [{
                    'hdop': 0.9,
                    'vdop': 1.4,
                    'pdop': 1.7,
                    'satellites': [
                        {'PRN': 12, 'el': 45, 'az': 120, 'ss': 38, 'used': True},
                        {'PRN': 5, 'el': 15, 'az': 210, 'ss': 19, 'used': False},
                        {'PRN': 24, 'el': 70, 'az': 310, 'ss': 44, 'used': True},
                    ],
                }],
            },
        ]

        result = parse_gpsd_messages(messages)
        self.assertTrue(result['connected'])
        self.assertEqual(result['version'], '3.25')
        self.assertEqual(result['fix']['mode'], 3)
        self.assertEqual(result['fix']['mode_label'], '3D Fix')
        self.assertAlmostEqual(result['fix']['lat'], -34.9285)
        self.assertAlmostEqual(result['fix']['alt'], 52.4)
        self.assertEqual(result['sky']['satellites_visible'], 3)
        self.assertEqual(result['sky']['satellites_used'], 2)
        self.assertEqual([s['PRN'] for s in result['sky']['satellites']], [24, 12, 5])

    def test_query_gpsd_socket_success(self):
        lines = [
            json.dumps({'class': 'VERSION', 'release': '3.25'}),
            json.dumps({
                'class': 'POLL',
                'tpv': [{'mode': 2, 'lat': 51.5, 'lon': -0.1}],
                'sky': [{'hdop': 1.2, 'satellites': [{'PRN': 3, 'ss': 30, 'used': True}]}],
            }),
        ]
        payload = ('\n'.join(lines) + '\n').encode('utf-8')
        fake_sock = _FakeSocket([payload])

        with patch('indi_allsky.gpsd_client.socket.create_connection', return_value=fake_sock):
            res = query_gpsd(host='127.0.0.1', port=2947)

        self.assertTrue(res['connected'])
        self.assertEqual(res['fix']['mode'], 2)
        self.assertEqual(res['fix']['mode_label'], '2D Fix')
        self.assertEqual(res['sky']['satellites_used'], 1)
        self.assertTrue(any(b'?POLL;' in chunk for chunk in fake_sock.sent))

    def test_query_gpsd_connection_error(self):
        with patch('indi_allsky.gpsd_client.socket.create_connection', side_effect=OSError('Connection refused')):
            res = query_gpsd()

        self.assertFalse(res['connected'])
        self.assertEqual(res['fix']['mode_label'], 'Disconnected')
        self.assertIn('Connection refused', res['error'])

    def test_nav_and_route_present(self):
        base_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'base.html').read_text(encoding='utf-8')
        views_py = (self.project_root / 'indi_allsky' / 'flask' / 'views.py').read_text(encoding='utf-8')
        gps_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'gps.html').read_text(encoding='utf-8')

        self.assertIn("('indi_allsky.gps_view', 'GPS Info', true)", base_html)
        self.assertIn("bp_allsky.add_url_rule('/gps'", views_py)
        self.assertIn("bp_allsky.add_url_rule('/js/gps'", views_py)
        self.assertIn('gps_satellites_body', gps_html)


if __name__ == '__main__':
    unittest.main()
