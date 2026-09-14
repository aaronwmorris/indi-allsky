from multiprocessing import Array, Queue
import time
import socket
import ssl
import json
import requests
from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.adsb import AdsbAircraftHttpWorker
from indi_allsky import constants


def test_adsb_calculations():
    # Latitude=0, Longitude=1, Elevation=2
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {
        'ADSB': {
            'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json',
            'ALT_DEG_MIN': 1.0,
        }
    }

    worker = AdsbAircraftHttpWorker(0, config, q, position_av)

    # Test conversions
    assert round(worker.m2ft(100), 1) == 328.1
    assert round(worker.km2mi(100), 1) == 62.1

    # Test haversine and dropoff
    dist = worker.haversine(138.6007, -34.9285, 138.6007, -35.0)
    assert dist > 0

    drop = worker.dropoff(dist)
    assert drop > 0

    # Test adsb_calculate with simulated dump1090 aircraft JSON
    adsb_data = {
        'now': time.time(),
        'aircraft': [
            {
                'hex': '7c6d22',
                'flight': 'QFA123 ',
                'lat': -34.93,
                'lon': 138.61,
                'alt_geom': 30000,
            },
            {
                'hex': '7c6d23',
                'flight': 'GROUND1',
                'lat': -34.92,
                'lon': 138.60,
                'alt_geom': 'ground',
            }
        ]
    }

    results = worker.adsb_calculate(adsb_data)
    assert len(results) == 1
    assert results[0]['id'] == 'QFA123'
    assert results[0]['flight'] == 'QFA123'
    assert 'altitude' in results[0]
    assert 'range' in results[0]


def test_adsb_calculate_edge_cases():
    # Observer at lat 10.0, lon 10.0
    position_av = Array('f', [10.0, 10.0, 50.0, 0.0, 0.0])
    q = Queue()
    config = {
        'ADSB': {
            'ALT_DEG_MIN': 5.0,
        }
    }
    worker = AdsbAircraftHttpWorker(0, config, q, position_av)

    adsb_data = {
        'now': time.time(),
        'aircraft': [
            # Uses alt_baro, aircraft to the west (lon < 10, long_dist_m negative), squawk as ID
            {
                'squawk': '1200',
                'lat': 10.01,
                'lon': 9.99,
                'alt_baro': 35000,
            },
            # Uses altitude fallback, hex as ID, angle <= 90
            {
                'hex': 'ABCDEF',
                'lat': 10.02,
                'lon': 10.02,
                'altitude': 25000,
            },
            # No flight, squawk, hex -> Unknown ID
            {
                'lat': 10.01,
                'lon': 10.01,
                'altitude': 20000,
            },
            # Missing altitude entirely -> skipped
            {
                'hex': 'NOALT',
                'lat': 10.01,
                'lon': 10.01,
            },
            # Altitude is None -> skipped
            {
                'hex': 'NONEALT',
                'lat': 10.01,
                'lon': 10.01,
                'altitude': None,
            },
            # Missing lat/lon (KeyError) -> skipped
            {
                'hex': 'NOLAT',
                'alt_geom': 10000,
            },
            # Below horizon (very low altitude far away) -> skipped
            {
                'hex': 'BELOWHORIZON',
                'lat': 12.0,
                'lon': 12.0,
                'altitude': 10,  # 10 feet at >200km is below dropoff
            },
            # Greater than 250km away (> 250000m warning) and below min altitude (alt < 5.0) -> skipped
            {
                'hex': 'DISTANT',
                'lat': 12.335,
                'lon': 10.0,
                'alt_geom': 45000,
            },

        ]
    }

    results = worker.adsb_calculate(adsb_data)
    ids = [r['id'] for r in results]
    assert '1200' in ids
    assert 'ABCDEF' in ids
    assert 'Unknown' in ids
    assert 'NOALT' not in ids
    assert 'NONEALT' not in ids
    assert 'NOLAT' not in ids
    assert 'BELOWHORIZON' not in ids
    assert 'DISTANT' not in ids


def test_adsb_worker_run_success():
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {
        'ADSB': {
            'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json',
            'USERNAME': 'user',
            'PASSWORD': 'pass',
            'CERT_BYPASS': False,
            'ALT_DEG_MIN': 1.0,
        }
    }

    worker = AdsbAircraftHttpWorker(1, config, q, position_av)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'now': time.time(),
        'aircraft': [
            {
                'hex': '7c6d22',
                'flight': 'TEST1',
                'lat': -34.93,
                'lon': 138.61,
                'alt_geom': 30000,
            }
        ]
    }

    with patch('requests.get', return_value=mock_resp) as mock_get:
        worker.run()
        mock_get.assert_called_once()
        assert mock_get.call_args[1]['verify'] is True
        assert mock_get.call_args[1]['auth'] is not None

    data = q.get(timeout=1.0)
    assert len(data) == 1
    assert data[0]['flight'] == 'TEST1'


def test_adsb_worker_run_http_error():
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {'ADSB': {'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json'}}
    worker = AdsbAircraftHttpWorker(1, config, q, position_av)

    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch('requests.get', return_value=mock_resp):
        worker.run()

    data = q.get(timeout=1.0)
    assert data == []


def test_adsb_worker_run_json_error():
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {'ADSB': {'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json'}}
    worker = AdsbAircraftHttpWorker(1, config, q, position_av)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

    with patch('requests.get', return_value=mock_resp):
        worker.run()

    data = q.get(timeout=1.0)
    assert data == []


def test_adsb_worker_run_out_of_date():
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {'ADSB': {'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json'}}
    worker = AdsbAircraftHttpWorker(1, config, q, position_av)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'now': time.time() - 100,  # > 60 seconds ago
        'aircraft': []
    }

    with patch('requests.get', return_value=mock_resp):
        worker.run()

    data = q.get(timeout=1.0)
    assert data == []


@pytest.mark.parametrize(
    "exception_to_raise",
    [
        socket.gaierror("DNS failed"),
        socket.timeout("Socket timeout"),
        requests.exceptions.ConnectTimeout("Connect timeout"),
        ssl.SSLCertVerificationError("SSL cert error"),
        requests.exceptions.SSLError("SSL error"),
        requests.exceptions.ConnectionError("Connection error"),
        requests.exceptions.ReadTimeout("Read timeout"),
    ],
)
def test_adsb_worker_run_network_exceptions(exception_to_raise):
    position_av = Array('f', [-34.9285, 138.6007, 50.0, 0.0, 0.0])
    q = Queue()
    config = {'ADSB': {'DUMP1090_URL': 'http://localhost:8080/data/aircraft.json'}}
    worker = AdsbAircraftHttpWorker(1, config, q, position_av)

    with patch('requests.get', side_effect=exception_to_raise):
        worker.run()

    data = q.get(timeout=1.0)
    assert data == []

