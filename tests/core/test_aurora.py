import json
import statistics
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from indi_allsky.aurora import (
    IndiAllskyAuroraUpdate,
    AuroraDataUpdateFailure,
    AuroraDataProcessingError,
)

@pytest.fixture
def aurora(flask_app):
    config = {}
    return IndiAllskyAuroraUpdate(config)


def test_init(flask_app):
    config = {'test': 123}
    aurora = IndiAllskyAuroraUpdate(config)
    assert aurora.config == config
    assert aurora.ovation_json_data is None
    assert aurora.kpindex_json_data is None
    assert aurora.solar_wind_mag_json_data is None
    assert aurora.solar_wind_plasma_json_data is None
    assert aurora.hemi_power_data is None


def test_processOvationLocationData_positive_long(aurora):
    json_data = {
        'coordinates': [
            # [long, lat, value]
            [10, 20, 5],
            [10, 21, 15],
            [200, 20, 25],  # Out of range
        ]
    }
    # For lat 20, long 10.
    # Grid: lat: 20-7 to 20+7 = 13 to 27
    # long: 10-9 to 10+9 = 1 to 19
    max_val, avg_val = aurora.processOvationLocationData(json_data, 20.0, 10.0)
    assert max_val == 15
    assert avg_val == 10.0


def test_processOvationLocationData_negative_long(aurora):
    json_data = {
        'coordinates': [
            # [long, lat, value]
            [350, 20, 5],
            [351, 20, 15],
            [10, 20, 25],  # Out of range
        ]
    }
    # For lat 20, long -10. => converted to 350
    # Grid: lat: 13 to 27
    # long: 350-9 to 350+9 = 341 to 359 (and some wraparound, but since the bug exists in the code, it just looks for exactly those numbers)
    max_val, avg_val = aurora.processOvationLocationData(json_data, 20.0, -10.0)
    assert max_val == 15
    assert avg_val == 10.0


def test_processOvationLocationData_empty(aurora):
    json_data = {
        'coordinates': [
            [100, 100, 5],
        ]
    }
    with pytest.raises(ValueError):
        aurora.processOvationLocationData(json_data, 20.0, 10.0)


def test_processKpindexPoly_valid(aurora):
    json_data = [
        {'Kp': '1.0'},
        {'Kp': '2.0'},
        {'Kp': '3.0'}
    ]
    kp_last, p_converted = aurora.processKpindexPoly(json_data)
    assert kp_last == 3.0
    # y = 1 + 1*x => coef[0] = 1, coef[1] = 1
    # x is 0, 1, 2. y is 1, 2, 3
    assert pytest.approx(p_converted.coef[0]) == 1.0
    assert pytest.approx(p_converted.coef[1]) == 1.0


def test_processKpindexPoly_invalid_skipped(aurora):
    json_data = [
        {'Kp': '1.0'},
        {'Kp': 'invalid'},
        {'Kp': '2.0'}
    ]
    kp_last, p_converted = aurora.processKpindexPoly(json_data)
    assert kp_last == 2.0
    # x is 0, 1. y is 1, 2. coef should be 1 + 1*x
    assert pytest.approx(p_converted.coef[0]) == 1.0
    assert pytest.approx(p_converted.coef[1]) == 1.0


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindMagData(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_datetime.strptime.side_effect = datetime.strptime

    json_data = [
        # Valid and recent
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'bt': '5.0', 'bz_gsm': '2.0'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:55:00', 'bt': '7.0', 'bz_gsm': '4.0'},
        # Old (skipped)
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:30:00', 'bt': '10.0', 'bz_gsm': '10.0'},
        # Wrong source (skipped)
        {'source': 'ACE', 'time_tag': '2023-01-01T11:55:00', 'bt': '10.0', 'bz_gsm': '10.0'},
        # Null values (skipped)
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:55:00', 'bt': None, 'bz_gsm': '4.0'},
    ]

    mean_bt, mean_bz = aurora.processSolarWindMagData(json_data)
    assert mean_bt == 6.0
    assert mean_bz == 3.0


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindMagData_empty(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    
    with pytest.raises(statistics.StatisticsError):
        aurora.processSolarWindMagData([])


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindPlasmaData(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_datetime.strptime.side_effect = datetime.strptime

    json_data = [
        # Valid and recent
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'proton_density': '2.0', 'proton_speed': '400.0', 'proton_temperature': '100000'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:55:00', 'proton_density': '4.0', 'proton_speed': '600.0', 'proton_temperature': '300000'},
        # Old
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:30:00', 'proton_density': '10.0', 'proton_speed': '1000.0', 'proton_temperature': '500000'},
        # Null
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'proton_density': None, 'proton_speed': '400.0', 'proton_temperature': '100000'},
    ]

    density, speed, temp = aurora.processSolarWindPlasmaData(json_data)
    assert density == 3.0
    assert speed == 500.0
    assert temp == 200000


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindPlasmaData_empty(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    
    with pytest.raises(statistics.StatisticsError):
        aurora.processSolarWindPlasmaData([])


def test_processHemiPowerData(aurora):
    text_data = """# This is a comment
# Another comment
2023-01-01_12:00 2023-01-01_12:30 15 20
2023-01-01_12:05 2023-01-01_12:35 18 25
"""
    n_gw, s_gw = aurora.processHemiPowerData(text_data)
    assert n_gw == 18
    assert s_gw == 25


def test_processHemiPowerData_empty(aurora):
    with pytest.raises(IndexError):
        aurora.processHemiPowerData("# only comments\n")


@patch('indi_allsky.aurora.requests.get')
def test_download_json_success(mock_get, aurora):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"key": "value"}'
    mock_get.return_value = mock_response

    result = aurora.download_json('http://test')
    assert result == {'key': 'value'}
    mock_get.assert_called_once()


@patch('indi_allsky.aurora.requests.get')
def test_download_json_error(mock_get, aurora):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = aurora.download_json('http://test')
    assert result is None


@patch('indi_allsky.aurora.requests.get')
def test_download_txt_success(mock_get, aurora):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = 'text data'
    mock_get.return_value = mock_response

    result = aurora.download_txt('http://test')
    assert result == 'text data'


@patch('indi_allsky.aurora.requests.get')
def test_download_txt_error(mock_get, aurora):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    result = aurora.download_txt('http://test')
    assert result is None
