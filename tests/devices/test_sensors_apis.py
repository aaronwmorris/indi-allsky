import sys
from multiprocessing import Array
from unittest.mock import MagicMock, patch
import pytest

# Provide fallbacks for optional embedded hardware modules if not installed
if 'micropython' not in sys.modules:
    mock_mp = MagicMock()
    mock_mp.const = lambda x: x
    sys.modules['micropython'] = mock_mp

if 'adafruit_bus_device' not in sys.modules:
    mock_abd = MagicMock()
    sys.modules['adafruit_bus_device'] = mock_abd
    sys.modules['adafruit_bus_device.i2c_device'] = mock_abd.i2c_device

if 'busio' not in sys.modules:
    mock_busio = MagicMock()
    sys.modules['busio'] = mock_busio

from indi_allsky.devices.sensors.tempApiDeepSkyDad import TempApiDeepSkyDad
from indi_allsky.devices.sensors.adafruit_mlx90615 import MLX90615


def test_temp_api_deepskydad_update():
    config = {}
    sensor = TempApiDeepSkyDad(config, "TestDSD", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.url = "http://localhost:8080/ace_api/overlays"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "fv": 1,
        "ht": 30.5,
        "hv": 0,
        "oc": 18.2,
        "oe": 1,
        "rc": 240.0,
        "sh": 35.0,
        "st": 28.0,
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 8
        assert data['data'][0] == 1
        assert data['data'][1] == 30.5

        # Calling update again before next_run returns cached data without calling requests.get
        data_cached = sensor.update()
        assert data_cached == data


def test_mlx90615_driver():
    fake_i2c = MagicMock()
    with patch('adafruit_bus_device.i2c_device.I2CDevice') as mock_i2c_dev_cls:
        mock_i2c_dev = MagicMock()
        mock_i2c_dev.__enter__.return_value = mock_i2c_dev
        mock_i2c_dev_cls.return_value = mock_i2c_dev

        mlx = MLX90615(fake_i2c, address=0x5B)
        # Mock _read_16 to return 15000 (15000 * 0.02 - 273.15 = 26.85 C)
        with patch.object(mlx, '_read_16', return_value=15000):
            assert pytest.approx(mlx.ambient_temperature, 0.1) == 26.85
            assert pytest.approx(mlx.object_temperature, 0.1) == 26.85
