from multiprocessing import Array
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.devices.sensors.tempSensorBme280 import TempSensorBme280
from indi_allsky.devices.sensors.tempSensorBme680 import TempSensorBme680
from indi_allsky.devices.sensors.tempSensorBmp280 import TempSensorBmp280
from indi_allsky.devices.sensors.tempSensorBmp3xx import TempSensorBmp3xx
from indi_allsky.devices.sensors.tempSensorSht3x import TempSensorSht3x
from indi_allsky.devices.sensors.tempSensorSht4x import TempSensorSht4x
from indi_allsky.devices.sensors.tempSensorSi7021 import TempSensorSi7021
from indi_allsky.devices.sensors.tempSensorHtu21d import TempSensorHtu21d
from indi_allsky.devices.sensors.tempSensorHtu31d import TempSensorHtu31d
from indi_allsky.devices.sensors.lightSensorTsl2561 import LightSensorTsl2561
from indi_allsky.devices.sensors.tempSensorDht import TempSensorDht2x
from indi_allsky.devices.sensors.currentSensorIna219 import CurrentSensorIna219
from indi_allsky.devices.sensors.currentSensorIna3221 import CurrentSensorIna3221
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
    assert data['data'][3] == pytest.approx(10.0, abs=0.5)
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
        humidity=50.0,
        pressure=1000.0,
        gas=15000,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 5
    # Fahrenheit check (20C = 68F)
    assert data['data'][0] == 68.0
    assert data['data'][1] == 50.0
    assert data['data'][2] == pytest.approx(29.53, abs=0.01)
    assert data['data'][3] == 15000
    assert data['data'][4] == pytest.approx(48.7, abs=0.5)


def test_bmp280_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBmp280(config, "TestBmp280", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bmp280 = MagicMock(
        temperature=24.0,
        pressure=1010.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 2
    assert data['data'][0] == 24.0
    assert data['data'][1] == 1010.0


def test_bmp3xx_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBmp3xx(config, "TestBmp3xx", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bmp3xx = MagicMock(
        temperature=21.0,
        pressure=1012.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 2
    assert data['data'][0] == 21.0
    assert data['data'][1] == 1012.0


def test_sht3x_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSht3x(config, "TestSht3x", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_night = False
    sensor.heater_day = False
    sensor.heater_available = False
    sensor.sht3x = MagicMock(
        temperature=23.0,
        relative_humidity=55.0,
        heater=False,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 23.0
    assert data['data'][1] == 55.0


def test_sht4x_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSht4x(config, "TestSht4x", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.mode_night = 0
    sensor.mode_day = 0
    sensor.heater_available = False
    sensor.sht4x = MagicMock(
        measurements=(25.0, 50.0),
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 25.0
    assert data['data'][1] == 50.0


def test_si7021_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSi7021(config, "TestSi7021", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_level_night = -1
    sensor.heater_level_day = -1
    sensor.heater_available = False
    sensor.si7021 = MagicMock(
        temperature=22.0,
        relative_humidity=60.0,
        heater_enable=False,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 22.0
    assert data['data'][1] == 60.0


def test_htu21d_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    sensor = TempSensorHtu21d(config, "TestHtu21d", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.htu21d = MagicMock(
        temperature=19.5,
        relative_humidity=52.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 19.5
    assert data['data'][1] == 52.0


def test_htu31d_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorHtu31d(config, "TestHtu31d", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_night = False
    sensor.heater_day = False
    sensor.heater_available = False
    sensor.htu31d = MagicMock(
        temperature=20.5,
        relative_humidity=48.0,
        heater=False,
    )


    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 20.5
    assert data['data'][1] == 48.0


def test_ina219_update():
    config = {}
    sensor = CurrentSensorIna219(config, "TestIna219", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.ina219 = MagicMock(
        bus_voltage=12.0,
        shunt_voltage=0.05,
        current=500.0,  # 500 mA
        power=6.0,      # 6 Watts
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 12.05
    assert data['data'][1] == 0.5
    assert data['data'][2] == 6.0


def test_ina3221_get_channel():
    config = {}
    sensor = CurrentSensorIna3221(config, "TestIna3221", Array('i', [0]*10), Array('f', [0.0]*10))
    mock_ch0 = MagicMock(bus_voltage=12.0, shunt_voltage=0.01, current=1.0)
    sensor.ina3221 = (mock_ch0,)

    v, a, w = sensor.getChannel(0)
    assert v == 12.0
    assert a == 1000.0
    assert w == 12000.0


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
    assert data['data'][2] == pytest.approx(10.1, abs=0.5)
