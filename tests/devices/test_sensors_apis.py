import json
import socket
import ssl
import sys
from multiprocessing import Array
from unittest.mock import MagicMock, patch
import pytest
import requests

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

from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky.devices.sensors.tempApiDeepSkyDad import TempApiDeepSkyDad
from indi_allsky.devices.sensors.adafruit_mlx90615 import MLX90615
from indi_allsky.devices.sensors.tempApiAmbientWeather import TempApiAmbientWeather
from indi_allsky.devices.sensors.tempApiOpenWeatherMap import TempApiOpenWeatherMap
from indi_allsky.devices.sensors.tempApiWeatherUnderground import TempApiWeatherUnderground
from indi_allsky.devices.sensors.tempApiEcowitt import TempApiEcowitt
from indi_allsky.devices.sensors.tempApiAstrospheric import TempApiAstrospheric


ALL_NETWORK_EXCEPTIONS = [
    socket.gaierror("lookup fail"),
    socket.timeout("timed out"),
    requests.exceptions.ConnectTimeout("timeout"),
    requests.exceptions.ConnectionError("offline"),
    requests.exceptions.ReadTimeout("read timeout"),
    ssl.SSLCertVerificationError("cert fail"),
    requests.exceptions.SSLError("ssl err"),
]


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- MLX90615 Driver ---

def test_mlx90615_driver():
    fake_i2c = MagicMock()
    with patch('adafruit_bus_device.i2c_device.I2CDevice') as mock_i2c_dev_cls:
        mock_i2c_dev = MagicMock()
        mock_i2c_dev.__enter__.return_value = mock_i2c_dev
        mock_i2c_dev_cls.return_value = mock_i2c_dev

        def fake_write_then_readinto(out_buf, in_buf, out_end=1):
            # 15000 = 0x3A98 -> in_buf[0] = 0x98, in_buf[1] = 0x3A
            in_buf[0] = 0x98
            in_buf[1] = 0x3A

        mock_i2c_dev.write_then_readinto.side_effect = fake_write_then_readinto

        mlx = MLX90615(fake_i2c, address=0x5B)
        assert pytest.approx(mlx.ambient_temperature, 0.1) == 26.85
        assert pytest.approx(mlx.object_temperature, 0.1) == 26.85


def test_mlx90615_busio_import_error():
    import importlib
    with patch.dict(sys.modules, {'busio': None}):
        import indi_allsky.devices.sensors.adafruit_mlx90615 as mlx_mod
        importlib.reload(mlx_mod)
        assert mlx_mod.I2C is None
    import indi_allsky.devices.sensors.adafruit_mlx90615 as mlx_mod
    importlib.reload(mlx_mod)


# --- DeepSkyDad ---

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

        # Cached data
        data_cached = sensor.update()
        assert data_cached == data


def test_temp_api_deepskydad_errors():
    config = {}
    sensor = TempApiDeepSkyDad(config, "TestDSD", Array('i', [0]*10), Array('f', [0.0]*10))

    # HTTP error
    mock_resp = MagicMock(status_code=500)
    with patch('requests.get', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='DeepSkyDad API returned 500'):
            sensor.update()

    # Network exceptions
    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.get', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    # JSONDecodeError
    mock_resp_json_err = MagicMock(status_code=200)
    mock_resp_json_err.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.get', return_value=mock_resp_json_err):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


# --- Ambient Weather ---

def test_temp_api_ambient_weather_init_errors():
    empty_cfg = {'TEMP_SENSOR': {}}
    with pytest.raises(Exception, match='Ambient Weather API key is empty'):
        TempApiAmbientWeather(empty_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))

    no_app_cfg = {'TEMP_SENSOR': {'AMBIENTWEATHER_APIKEY': 'k'}}
    with pytest.raises(Exception, match='Ambient Weather Application key is empty'):
        TempApiAmbientWeather(no_app_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))

    no_mac_cfg = {'TEMP_SENSOR': {'AMBIENTWEATHER_APIKEY': 'k', 'AMBIENTWEATHER_APPLICATIONKEY': 'a'}}
    with pytest.raises(Exception, match='Ambient Weather Device MAC address is empty'):
        TempApiAmbientWeather(no_mac_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))


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
            "winddir": 180.0,
            "hourlyrainin": 0.5,
            "solarradiation": 100.0,
            "uv": 3.0,
        }
    ]

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 10

        # Cached
        assert sensor.update() == data

        # TEMP_DISPLAY options: f, k, c
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == 68.0

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(293.15, abs=0.1)

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        assert sensor.update()['data'][0] == pytest.approx(20.0, abs=0.1)

        # WINDSPEED_DISPLAY options: mph, knots, kph, default
        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mph'
        assert sensor.update()['data'][4] == 5.0

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'knots'
        assert sensor.update()['data'][4] == pytest.approx(4.34, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'kph'
        assert sensor.update()['data'][4] == pytest.approx(8.05, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mps'
        assert sensor.update()['data'][4] == pytest.approx(2.235, abs=0.1)

        # PRESSURE_DISPLAY options: psi, inHg, mmHg, default (hpa)
        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor.update()['data'][3] == pytest.approx(433.95, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor.update()['data'][3] == 29.92

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor.update()['data'][3] == pytest.approx(760.0, abs=1.0)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'hpa'
        assert sensor.update()['data'][3] == pytest.approx(1013.2, abs=1.0)

        # ValueError in dew point
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("err")):
            assert sensor.update()['dew_point'] == 0.0

        # Empty item in response (fallback to 0.0 defaults)
        sensor.next_run = 0
        mock_resp.json.return_value = [{}]
        empty_data = sensor.update()
        assert empty_data['data'][0] == pytest.approx(-17.77, abs=0.1)  # 0.0 F in C


def test_temp_api_ambient_weather_errors():
    config = {
        'TEMP_SENSOR': {
            'AMBIENTWEATHER_APIKEY': 'k',
            'AMBIENTWEATHER_APPLICATIONKEY': 'a',
            'AMBIENTWEATHER_MACADDRESS': 'm',
        }
    }
    sensor = TempApiAmbientWeather(config, "TestAmbient", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock(status_code=403)
    with patch('requests.get', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='Ambient Weather API returned 403'):
            sensor.update()

    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.get', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    mock_resp_json = MagicMock(status_code=200)
    mock_resp_json.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.get', return_value=mock_resp_json):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


# --- OpenWeatherMap ---

def test_temp_api_openweathermap_init_errors():
    with pytest.raises(Exception, match='OpenWeatherMap API key is empty'):
        TempApiOpenWeatherMap(
            {'LOCATION_LATITUDE': 0, 'LOCATION_LONGITUDE': 0, 'TEMP_SENSOR': {}},
            "Test", Array('i', [0]*10), Array('f', [0.0]*10),
        )


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
        "wind": {"speed": 3.5, "gust": 5.0, "deg": 180},
        "rain": {"1h": 2.5},
        "snow": {"1h": 1.0},
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 10

        # Cached
        assert sensor.update() == data

        # TEMP_DISPLAY: f, k, c
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == 68.0

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(293.15)

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        assert sensor.update()['data'][0] == 20.0

        # WINDSPEED_DISPLAY: mph, knots, kph, mps
        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mph'
        assert sensor.update()['data'][5] == pytest.approx(7.83, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'knots'
        assert sensor.update()['data'][5] == pytest.approx(6.8, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'kph'
        assert sensor.update()['data'][5] == pytest.approx(12.6, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mps'
        assert sensor.update()['data'][5] == 3.5

        # PRESSURE_DISPLAY: psi, inHg, mmHg, hpa
        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor.update()['data'][3] == pytest.approx(14.69, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor.update()['data'][3] == pytest.approx(29.91, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor.update()['data'][3] == pytest.approx(759.8, abs=1.0)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'hpa'
        assert sensor.update()['data'][3] == 1013.0

        # Dew point ValueError
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("err")):
            assert sensor.update()['dew_point'] == 0.0

        # Missing optional sections: wind, rain, snow
        sensor.next_run = 0
        mock_resp.json.return_value = {
            "main": {"temp": 20.0, "feels_like": 19.5, "humidity": 55.0, "pressure": 1013.0},
            "clouds": {"all": 0},
        }
        sparse_data = sensor.update()
        assert sparse_data['data'][5] == 0.0  # wind speed
        assert sparse_data['data'][7] == 0.0  # rain
        assert sparse_data['data'][8] == 0.0  # snow


def test_temp_api_openweathermap_errors():
    config = {
        'LOCATION_LATITUDE': 0, 'LOCATION_LONGITUDE': 0,
        'TEMP_SENSOR': {'OPENWEATHERMAP_APIKEY': 'k'},
    }
    sensor = TempApiOpenWeatherMap(config, "TestOWM", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock(status_code=401)
    with patch('requests.get', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='OpenWeatherMap API returned 401'):
            sensor.update()

    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.get', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    mock_resp_json = MagicMock(status_code=200)
    mock_resp_json.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.get', return_value=mock_resp_json):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


# --- Weather Underground ---

def test_temp_api_weather_underground_init_errors():
    with pytest.raises(Exception, match='Weather Underground API key is empty'):
        TempApiWeatherUnderground(
            {'TEMP_SENSOR': {}}, "Test", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='STATION1',
        )


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
                    "pressure": 1015.0,
                    "windSpeed": 10.0,
                    "windGust": 15.0,
                    "precipTotal": 2.5,
                    "solarRadiation": 50.0,
                    "uv": 1.0,
                    "dewpt": 11.0,
                },
                "humidity": 65.0,
                "winddir": 90,
                "solarRadiation": 50.0,
                "uv": 1.0,
            }
        ]
    }

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 9

        # Cached
        assert sensor.update() == data

        # TEMP_DISPLAY: f, k, c
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == pytest.approx(64.4)

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(291.15)

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        assert sensor.update()['data'][0] == 18.0

        # WINDSPEED_DISPLAY: mph, knots, kph, mps
        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mph'
        assert sensor.update()['data'][3] == pytest.approx(22.37, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'knots'
        assert sensor.update()['data'][3] == pytest.approx(19.44, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'kph'
        assert sensor.update()['data'][3] == pytest.approx(36.0, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mps'
        assert sensor.update()['data'][3] == 10.0

        # PRESSURE_DISPLAY: psi, inHg, mmHg, hpa
        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor.update()['data'][2] == pytest.approx(14.72, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor.update()['data'][2] == pytest.approx(29.97, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor.update()['data'][2] == pytest.approx(761.3, abs=1.0)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'hpa'
        assert sensor.update()['data'][2] == 1015.0

        # Dew point ValueError
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("err")):
            assert sensor.update()['dew_point'] == 0.0

        # Missing temp / humidity in response
        sensor.next_run = 0
        mock_resp.json.return_value = {"observations": [{"metric_si": {}}]}
        sparse = sensor.update()
        assert sparse['data'][0] == 0.0


def test_temp_api_weather_underground_errors():
    config = {'TEMP_SENSOR': {'WUNDERGROUND_APIKEY': 'k'}}
    sensor = TempApiWeatherUnderground(config, "TestWund", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='S1')

    mock_resp = MagicMock(status_code=404)
    with patch('requests.get', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='Weather Underground API returned 404'):
            sensor.update()

    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.get', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    mock_resp_json = MagicMock(status_code=200)
    mock_resp_json.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.get', return_value=mock_resp_json):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


# --- Ecowitt ---

def test_temp_api_ecowitt_init_errors():
    empty_cfg = {'TEMP_SENSOR': {}}
    with pytest.raises(Exception, match='Ecowitt API key is empty'):
        TempApiEcowitt(empty_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))

    no_app_cfg = {'TEMP_SENSOR': {'ECOWITT_APIKEY': 'k'}}
    with pytest.raises(Exception, match='Ecowitt Application key is empty'):
        TempApiEcowitt(no_app_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))

    no_mac_cfg = {'TEMP_SENSOR': {'ECOWITT_APIKEY': 'k', 'ECOWITT_APPLICATIONKEY': 'a'}}
    with pytest.raises(Exception, match='Ecowitt Device MAC address is empty'):
        TempApiEcowitt(no_mac_cfg, "Test", Array('i', [0]*10), Array('f', [0.0]*10))


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
                "feels_like": {"value": "71.0"},
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
                "rain_rate": {"value": "0.5"},
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

        # Cached
        assert sensor.update() == data

        # TEMP_DISPLAY: f, k, c
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == 72.0

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(295.37, abs=0.1)

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        assert sensor.update()['data'][0] == pytest.approx(22.22, abs=0.1)

        # WINDSPEED_DISPLAY: mph, knots, kph, mps
        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mph'
        assert sensor.update()['data'][4] == 5.0

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'knots'
        assert sensor.update()['data'][4] == pytest.approx(4.34, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'kph'
        assert sensor.update()['data'][4] == pytest.approx(8.05, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mps'
        assert sensor.update()['data'][4] == pytest.approx(2.235, abs=0.1)

        # PRESSURE_DISPLAY options: psi, inHg, mmHg, hpa
        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor.update()['data'][3] == pytest.approx(433.95, abs=0.1)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor.update()['data'][3] == 29.92

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor.update()['data'][3] == pytest.approx(760.0, abs=1.0)

        sensor.next_run = 0
        sensor.config['PRESSURE_DISPLAY'] = 'hpa'
        assert sensor.update()['data'][3] == pytest.approx(1013.2, abs=1.0)

        # Dew point ValueError
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("err")):
            assert sensor.update()['dew_point'] == 0.0

        # Sparse values with rainfall_piezo
        sensor.next_run = 0
        mock_resp.json.return_value = {
            "code": 0,
            "data": {
                "outdoor": {
                    "temperature": {},
                    "feels_like": {},
                    "humidity": {},
                    "dew_point": {},
                },
                "pressure": {
                    "relative": {},
                },
                "wind": {
                    "wind_speed": {},
                    "wind_gust": {},
                    "wind_direction": {},
                },
                "rainfall_piezo": {
                    "rain_rate": {"value": "1.2"},
                },
                "solar_and_uvi": {},
            },
        }
        sparse = sensor.update()
        assert sparse['data'][0] == pytest.approx(-17.77, abs=0.1)  # 0.0 F in C
        assert sparse['data'][6] == 1.2

        sensor.next_run = 0
        mock_resp.json.return_value["data"]["rainfall_piezo"] = {}
        no_rain = sensor.update()
        assert no_rain['data'][6] == 0.0


def test_temp_api_ecowitt_errors():
    config = {
        'TEMP_SENSOR': {
            'ECOWITT_APIKEY': 'k',
            'ECOWITT_APPLICATIONKEY': 'a',
            'ECOWITT_MACADDRESS': 'm',
        }
    }
    sensor = TempApiEcowitt(config, "TestEco", Array('i', [0]*10), Array('f', [0.0]*10))

    # Code != 0
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"code": 40001, "msg": "invalid key"}
    with patch('requests.get', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='Ecowitt API returned "invalid key"'):
            sensor.update()

    # HTTP error
    mock_resp_400 = MagicMock(status_code=400)
    with patch('requests.get', return_value=mock_resp_400):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='Ecowitt API returned 400'):
            sensor.update()

    # Network error
    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.get', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    # JSON error
    mock_resp_json = MagicMock(status_code=200)
    mock_resp_json.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.get', return_value=mock_resp_json):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


# --- Astrospheric ---

def test_temp_api_astrospheric_init_errors():
    with pytest.raises(Exception, match='Astrospheric API key is empty'):
        TempApiAstrospheric(
            {'LOCATION_LATITUDE': 0, 'LOCATION_LONGITUDE': 0, 'TEMP_SENSOR': {}},
            "Test", Array('i', [0]*10), Array('f', [0.0]*10),
        )


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
        assert len(data['data']) == 6

        # Cached
        assert sensor.update() == data

        # TEMP_DISPLAY: f, k, c
        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == 68.0

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == 293.15

        sensor.next_run = 0
        sensor.config['TEMP_DISPLAY'] = 'c'
        assert sensor.update()['data'][0] == 20.0

        # WINDSPEED_DISPLAY: mph, knots, kph, mps
        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mph'
        assert sensor.update()['data'][4] == pytest.approx(11.18, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'knots'
        assert sensor.update()['data'][4] == pytest.approx(9.72, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'kph'
        assert sensor.update()['data'][4] == pytest.approx(18.0, abs=0.1)

        sensor.next_run = 0
        sensor.config['WINDSPEED_DISPLAY'] = 'mps'
        assert sensor.update()['data'][4] == 5.0

        # Frost point ValueError
        sensor.next_run = 0
        with patch.object(sensor, 'get_frost_point_c', side_effect=ValueError("err")):
            assert sensor.update()['frost_point'] == 0.0


def test_temp_api_astrospheric_errors():
    config = {
        'LOCATION_LATITUDE': 0, 'LOCATION_LONGITUDE': 0,
        'TEMP_SENSOR': {'ASTROSPHERIC_APIKEY': 'k'},
    }
    sensor = TempApiAstrospheric(config, "TestAstro", Array('i', [0]*10), Array('f', [0.0]*10))

    mock_resp = MagicMock(status_code=403)
    with patch('requests.post', return_value=mock_resp):
        sensor.next_run = 0
        with pytest.raises(SensorReadException, match='Astrospheric API returned 403'):
            sensor.update()

    for exc in ALL_NETWORK_EXCEPTIONS:
        with patch('requests.post', side_effect=exc):
            sensor.next_run = 0
            with pytest.raises(SensorReadException):
                sensor.update()

    mock_resp_json = MagicMock(status_code=200)
    mock_resp_json.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    with patch('requests.post', return_value=mock_resp_json):
        sensor.next_run = 0
        with pytest.raises(SensorReadException):
            sensor.update()


