from multiprocessing import Array
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.devices.sensors.tempSensorBme280 import TempSensorBme280
from indi_allsky.devices.sensors.tempSensorBme680 import TempSensorBme680
from indi_allsky.devices.sensors.lightSensorTsl2561 import LightSensorTsl2561
from indi_allsky.devices.sensors.tempSensorDht import TempSensorDht2x
from indi_allsky import constants


def test_bme280_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBme280(config, "TestBme280", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bme280 = MagicMock(
        temperature=22.5,
        humidity=45.0,
        pressure=1013.25,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 4
    assert data['data'][0] == 22.5
    assert data['data'][1] == 45.0
    assert data['data'][2] == 1013.25
    assert 'dew_point' in data
    assert 'heat_index' in data


def test_bme680_update():
    config = {
        'TEMP_DISPLAY': 'f',
        'PRESSURE_DISPLAY': 'inHg',
    }
    sensor = TempSensorBme680(config, "TestBme680", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bme680 = MagicMock(
        temperature=20.0,
        relative_humidity=50.0,
        pressure=1000.0,
        gas=15000,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 5
    # Fahrenheit check (20C = 68F)
    assert data['data'][0] == 68.0


def test_tsl2561_update():
    config = {}
    sensor = LightSensorTsl2561(config, "TestTsl2561", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.tsl2561 = MagicMock(
        lux=250.0,
        broadband=3000,
        infrared=1200,
    )
    sensor.gain_night = 1
    sensor.gain_day = 0
    sensor.integration_night = 1
    sensor.integration_day = 1
    sensor.disable_day = False

    with patch('time.sleep', return_value=None):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 5
        assert data['data'][0] == 250.0
        assert data['data'][1] == 3000
        assert data['data'][2] == 1200


def test_dht_update():
    config = {'TEMP_DISPLAY': 'c'}
    sensor = TempSensorDht2x(config, "TestDht", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.dht = MagicMock(
        temperature=18.0,
        humidity=60.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 18.0
    assert data['data'][1] == 60.0
