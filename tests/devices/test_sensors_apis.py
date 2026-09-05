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
from indi_allsky.devices.sensors.tempApiAmbientWeather import TempApiAmbientWeather
from indi_allsky.devices.sensors.tempApiOpenWeatherMap import TempApiOpenWeatherMap
from indi_allsky.devices.sensors.tempApiWeatherUnderground import TempApiWeatherUnderground
from indi_allsky.devices.sensors.tempApiEcowitt import TempApiEcowitt
from indi_allsky.devices.sensors.tempApiAstrospheric import TempApiAstrospheric


def test_temp_api_deepskydad_update():
    config = {}
    sensor = TempApiDeepSkyDad(config, "TestDSD", Array('i', [0]*10), Array('f', [0.0]*10))

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
        assert data['data'] == (1, 30.5, 0, 18.2, 1, 240.0, 35.0, 28.0)

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


def test_temp_api_ambient_weather_update():
    config = {
        'TEMP_SENSOR': {
            'AMBIENTWEATHER_APIKEY': 'test_api_key',
            'AMBIENTWEATHER_APPLICATIONKEY': 'test_app_key',
            'AMBIENTWEATHER_MACADDRESS': '00:11:22:33:44:55',
        }
    }
    sensor = TempApiAmbientWeather(config, "TestAmbient", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "tempf": 68.0,
            "dewPoint": 45.0,
            "feelsLike": 67.0,
            "humidity": 50.0,
            "baromrelin": 29.92,
            "windspeedmph": 5.0,
            "windgustmph": 10.0,
            "hourlyrainin": 0.0,
            "solarradiation": 100.0,
            "uv": 3.0,
        }
    ]

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 10


def test_temp_api_openweathermap_update():
    config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'TEMP_SENSOR': {
            'OPENWEATHERMAP_APIKEY': 'test_owm_key',
        }
    }
    sensor = TempApiOpenWeatherMap(config, "TestOWM", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "main": {
            "temp": 20.0,
            "feels_like": 19.5,
            "humidity": 55.0,
            "pressure": 1013.0,
        },
        "clouds": {"all": 20},
        "wind": {"speed": 3.5, "gust": 5.0},
        "rain": {"1h": 0.0},
        "snow": {"1h": 0.0},
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 10


def test_temp_api_weather_underground_update():
    config = {
        'TEMP_SENSOR': {
            'WUNDERGROUND_APIKEY': 'test_wund_key',
        }
    }
    sensor = TempApiWeatherUnderground(
        config,
        "TestWund",
        Array('i', [0]*10),
        Array('f', [0.0]*10),
        pin_1_name='KCASANFR123',
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "observations": [
            {
                "metric_si": {
                    "temp": 18.0,
                    "humidity": 65.0,
                    "pressure": 1015.0,
                    "windSpeed": 10.0,
                    "windGust": 15.0,
                    "precipTotal": 0.0,
                    "solarRadiation": 50.0,
                    "uv": 1.0,
                    "dewpt": 11.0,
                }
            }
        ]
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 9


def test_temp_api_ecowitt_update():
    config = {
        'TEMP_SENSOR': {
            'ECOWITT_APIKEY': 'test_eco_api',
            'ECOWITT_APPLICATIONKEY': 'test_eco_app',
            'ECOWITT_MACADDRESS': '00:AA:BB:CC:DD:EE',
        }
    }
    sensor = TempApiEcowitt(config, "TestEco", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 0,
        "data": {
            "outdoor": {
                "temperature": {"value": "72.0"},
                "feels_like": {"value": "72.0"},
                "humidity": {"value": "45.0"},
                "dew_point": {"value": "50.0"},
            },
            "pressure": {
                "relative": {"value": "29.92"},
            },
            "wind": {
                "wind_speed": {"value": "5.0"},
                "wind_gust": {"value": "8.0"},
                "wind_direction": {"value": "180"},
            },
            "rainfall": {
                "hourly": {"value": "0.0"},
            },
            "solar_and_uvi": {
                "solar": {"value": "150.0"},
                "uvi": {"value": "4.0"},
            }
        }
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 10


def test_temp_api_astrospheric_update():
    config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'TEMP_SENSOR': {
            'ASTROSPHERIC_APIKEY': 'test_astro_key',
        }
    }
    sensor = TempApiAstrospheric(config, "TestAstro", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        'RDPS_Temperature': [{'Value': {'ActualValue': 293.15}}],
        'RDPS_DewPoint': [{'Value': {'ActualValue': 283.15}}],
        'Astrospheric_Seeing': [{'Value': {'ActualValue': 3.0}}],
        'Astrospheric_Transparency': [{'Value': {'ActualValue': 2.0}}],
        'RDPS_CloudCover': [{'Value': {'ActualValue': 15.0}}],
        'RDPS_WindVelocity': [{'Value': {'ActualValue': 5.0}}],
        'RDPS_WindDirection': [{'Value': {'ActualValue': 180.0}}],
    }

    with patch('requests.post', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data


