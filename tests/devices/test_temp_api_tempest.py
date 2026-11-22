import json
from types import SimpleNamespace

import pytest
import requests

from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky.devices.sensors import tempApiTempest


def _make_response(status_code=200, payload=None, json_error=False):
    def _json():
        if json_error:
            raise json.JSONDecodeError('Invalid JSON', '', 0)
        return payload

    return SimpleNamespace(status_code=status_code, json=_json)


SAMPLE_OBS_PAYLOAD = {
    'station_id': 12345,
    'obs': [
        {
            'timestamp': 1588948614,
            'air_temperature': 20.0,
            'feels_like': 19.0,
            'relative_humidity': 50.0,
            'barometric_pressure': 1013.25,
            'station_pressure': 1010.0,
            'wind_avg': 5.0,
            'wind_gust': 8.0,
            'wind_direction': 180,
            'precip_accum_last_1hr': 2.5,
            'solar_radiation': 350.0,
            'uv': 3.2,
            'brightness': 25000,
        }
    ],
    'status': {
        'status_code': 0,
        'status_message': 'SUCCESS',
    },
}


def test_tempest_requires_token():
    with pytest.raises(Exception, match='Tempest Personal Access Token is empty'):
        tempApiTempest.TempApiTempest({'TEMP_SENSOR': {}}, 'tempest', [], [])


def test_tempest_explicit_station_metric_and_cache(monkeypatch):
    calls = []

    def fake_get(url, params=None, verify=True, timeout=None):
        calls.append((url, params, verify, timeout))
        return _make_response(200, SAMPLE_OBS_PAYLOAD)

    monkeypatch.setattr(tempApiTempest.requests, 'get', fake_get)

    cfg = {
        'TEMP_SENSOR': {
            'TEMPEST_APIKEY': 'pat-secret-123',
            'TEMPEST_STATION_ID': '12345',
        },
    }
    sensor = tempApiTempest.TempApiTempest(cfg, 'tempest', [], [])
    result = sensor.update()

    assert len(calls) == 1
    assert calls[0][0] == 'https://swd.weatherflow.com/swd/rest/observations/station/12345'
    assert calls[0][1] == {'token': 'pat-secret-123'}
    assert calls[0][2] is True

    assert result['wind_degrees'] == pytest.approx(180.0)
    assert result['data'][0] == pytest.approx(20.0)
    assert result['data'][1] == pytest.approx(19.0)
    assert result['data'][2] == pytest.approx(50.0)
    assert result['data'][3] == pytest.approx(1013.25)
    assert result['data'][4] == pytest.approx(5.0)
    assert result['data'][5] == pytest.approx(8.0)
    assert result['data'][6] == pytest.approx(2.5)
    assert result['data'][7] == pytest.approx(350.0)
    assert result['data'][8] == pytest.approx(3.2)
    assert result['data'][9] == pytest.approx(25000.0)

    # Subsequent call within next_run_offset returns cached data without HTTP call
    cached = sensor.update()
    assert cached == result
    assert len(calls) == 1


def test_tempest_auto_discovers_station_id(monkeypatch):
    calls = []

    def fake_get(url, params=None, verify=True, timeout=None):
        calls.append((url, params))
        if url.endswith('/stations'):
            return _make_response(200, {
                'stations': [{'station_id': 98765}],
                'status': {'status_code': 0, 'status_message': 'SUCCESS'},
            })
        return _make_response(200, SAMPLE_OBS_PAYLOAD)

    monkeypatch.setattr(tempApiTempest.requests, 'get', fake_get)

    cfg = {
        'TEMP_SENSOR': {
            'TEMPEST_APIKEY': 'pat-secret-123',
            'TEMPEST_STATION_ID': '',
        },
    }
    sensor = tempApiTempest.TempApiTempest(cfg, 'tempest', [], [])
    sensor.update()

    assert [c[0] for c in calls] == [
        'https://swd.weatherflow.com/swd/rest/stations',
        'https://swd.weatherflow.com/swd/rest/observations/station/98765',
    ]
    assert sensor.station_id == '98765'


@pytest.mark.parametrize(
    'temp_disp,wind_disp,pres_disp,exp_temp,exp_rain,exp_wind,exp_pres',
    [
        ('f', 'mph', 'inHg', 68.0, 2.5 * 0.0393700787, 5.0 * 3.6 * 0.6213711922, 1013.25 * 0.02952998057228486),
        ('k', 'knots', 'psi', 293.15, 2.5, 5.0 * 1.9438445, 1013.25 * 0.014503768077999999),
        ('c', 'kph', 'mmHg', 20.0, 2.5, 18.0, 1013.25 * 0.7500637554192107),
    ],
)
def test_tempest_unit_conversions(
    monkeypatch, temp_disp, wind_disp, pres_disp, exp_temp, exp_rain, exp_wind, exp_pres
):
    monkeypatch.setattr(
        tempApiTempest.requests,
        'get',
        lambda *args, **kwargs: _make_response(200, SAMPLE_OBS_PAYLOAD),
    )

    cfg = {
        'TEMP_DISPLAY': temp_disp,
        'WINDSPEED_DISPLAY': wind_disp,
        'PRESSURE_DISPLAY': pres_disp,
        'TEMP_SENSOR': {
            'TEMPEST_APIKEY': 'pat-secret-123',
            'TEMPEST_STATION_ID': '12345',
        },
    }
    sensor = tempApiTempest.TempApiTempest(cfg, 'tempest', [], [])
    result = sensor.update()

    assert result['data'][0] == pytest.approx(exp_temp)
    assert result['data'][6] == pytest.approx(exp_rain)
    assert result['data'][4] == pytest.approx(exp_wind)
    assert result['data'][3] == pytest.approx(exp_pres)


@pytest.mark.parametrize(
    'response_obj',
    [
        _make_response(401, {}),
        _make_response(200, None, json_error=True),
        _make_response(200, {'obs': [], 'status': {'status_code': 0}}),
        _make_response(200, {'status': {'status_code': 401, 'status_message': 'UNAUTHORIZED'}}),
    ],
)
def test_tempest_api_errors_raise_sensor_read_exception(monkeypatch, response_obj):
    monkeypatch.setattr(tempApiTempest.requests, 'get', lambda *args, **kwargs: response_obj)

    cfg = {
        'TEMP_SENSOR': {
            'TEMPEST_APIKEY': 'pat-secret-123',
            'TEMPEST_STATION_ID': '12345',
        },
    }
    sensor = tempApiTempest.TempApiTempest(cfg, 'tempest', [], [])
    with pytest.raises(SensorReadException):
        sensor.update()


def test_tempest_network_error_raises_sensor_read_exception(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.exceptions.ConnectTimeout('timed out')

    monkeypatch.setattr(tempApiTempest.requests, 'get', raise_timeout)

    cfg = {
        'TEMP_SENSOR': {
            'TEMPEST_APIKEY': 'pat-secret-123',
            'TEMPEST_STATION_ID': '12345',
        },
    }
    sensor = tempApiTempest.TempApiTempest(cfg, 'tempest', [], [])
    with pytest.raises(SensorReadException):
        sensor.update()
