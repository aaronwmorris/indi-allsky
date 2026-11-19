import ctypes
from multiprocessing import Array
from unittest.mock import MagicMock, patch

from indi_allsky.devices.sensors.tempApiEcowitt import TempApiEcowitt
from indi_allsky.sensor import SensorWorker


def _create_ecowitt_sensor():
    config = {
        'TEMP_SENSOR': {
            'ECOWITT_APIKEY': 'test_apikey',
            'ECOWITT_APPLICATIONKEY': 'test_appkey',
            'ECOWITT_MACADDRESS': 'AA:BB:CC:DD:EE:FF',
        },
        'TEMP_DISPLAY': 'c',
        'WINDSPEED_DISPLAY': 'mps',
        'PRESSURE_DISPLAY': 'hPa',
    }
    return TempApiEcowitt(config, 'Ecowitt Test', [], [])


def test_ecowitt_missing_outdoor_block():
    sensor = _create_ecowitt_sensor()

    # Simulated response when outdoor array battery is depleted (Discussion #3313)
    response_payload = {
        'code': 0,
        'msg': 'success',
        'time': '1645678900',
        'data': {
            'pressure': {
                'relative': {'unit': 'inHg', 'value': '29.92'},
            },
            'wind': {
                'wind_speed': {'unit': 'mph', 'value': '10.0'},
                'wind_gust': {'unit': 'mph', 'value': '15.0'},
                'wind_direction': {'unit': 'deg', 'value': '270'},
            },
            'solar_and_uvi': {
                'solar': {'unit': 'W/m^2', 'value': '500.0'},
                'uvi': {'unit': '', 'value': '5'},
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()

    assert data is not None
    assert 'data' in data
    # Ensure update completed without KeyError and populated available readings
    readings = data['data']
    assert round(readings[0], 2) == round(sensor.f2c(0.0), 2)  # 0.0 F converted to C
    assert readings[2] == 0.0  # Humidity defaulted
    assert readings[3] > 0.0   # Pressure converted to hPa
    assert readings[4] > 0.0   # Wind speed converted
    assert data['wind_degrees'] == 270.0


def test_ecowitt_empty_data_block():
    sensor = _create_ecowitt_sensor()

    response_payload = {
        'code': 0,
        'msg': 'success',
        'time': '1645678900',
        'data': {},
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()

    assert data is not None
    assert 'data' in data
    assert round(data['data'][0], 2) == round(sensor.f2c(0.0), 2)


def test_ecowitt_non_numeric_values():
    sensor = _create_ecowitt_sensor()

    response_payload = {
        'code': 0,
        'msg': 'success',
        'data': {
            'outdoor': {
                'temperature': {'value': '--'},
                'humidity': {'value': None},
            },
            'pressure': {
                'relative': {'value': 'invalid'},
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()

    assert data is not None
    assert round(data['data'][0], 2) == round(sensor.f2c(0.0), 2)
    assert data['data'][2] == 0.0


def test_ecowitt_full_valid_response():
    sensor = _create_ecowitt_sensor()

    response_payload = {
        'code': 0,
        'msg': 'success',
        'time': '1645678900',
        'data': {
            'outdoor': {
                'temperature': {'value': '68.0'},
                'feels_like': {'value': '68.0'},
                'humidity': {'value': '50'},
                'dew_point': {'value': '48.0'},
            },
            'pressure': {
                'relative': {'value': '29.92'},
            },
            'wind': {
                'wind_speed': {'value': '5.0'},
                'wind_gust': {'value': '10.0'},
                'wind_direction': {'value': '180'},
            },
            'rainfall': {
                'rain_rate': {'value': '0.1'},
            },
            'solar_and_uvi': {
                'solar': {'value': '300.0'},
                'uvi': {'value': '3'},
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch('requests.get', return_value=mock_resp):
        data = sensor.update()

    assert data is not None
    readings = data['data']
    # 68°F = 20.0°C
    assert round(readings[0], 1) == 20.0
    assert readings[2] == 50.0
    assert data['wind_degrees'] == 180.0


def test_sensor_worker_exception_resilience():
    worker = MagicMock()
    worker.sensors_user_av = Array(ctypes.c_float, 100)

    # Sensor A fails with KeyError as in Discussion #3313
    failing_sensor = MagicMock()
    failing_sensor.name = 'Failing Sensor'
    failing_sensor.update.side_effect = KeyError('outdoor')

    # Sensor B succeeds and updates its slot
    working_sensor = MagicMock()
    working_sensor.name = 'Working Sensor'
    working_sensor.slot = 10
    working_sensor.update.return_value = {
        'data': (22.5, 45.0),
    }

    worker.sensors = [failing_sensor, working_sensor]

    # Execute update_sensors — should catch exception and not crash
    SensorWorker.update_sensors(worker)

    failing_sensor.update.assert_called_once()
    working_sensor.update.assert_called_once()
    assert worker.sensors_user_av[10] == 22.5
    assert worker.sensors_user_av[11] == 45.0
