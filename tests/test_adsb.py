from multiprocessing import Array, Queue
import time
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
                'flight': 'QFA123',
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
