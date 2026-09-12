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


def test_processOvationLocationData_wrap_around(aurora):
    # longitude near 1.0 (triggers i < 0 wrap-around in long_list)
    json_data_low = {'coordinates': [[1, 20, 10]]}
    max_val, avg_val = aurora.processOvationLocationData(json_data_low, 20.0, 1.0)
    assert max_val == 10

    # longitude near 359.0 (triggers i > 360 wrap-around in long_list)
    json_data_high = {'coordinates': [[359, 20, 20]]}
    max_val, avg_val = aurora.processOvationLocationData(json_data_high, 20.0, 359.0)
    assert max_val == 20


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindMagData_none_fields(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_datetime.strptime.side_effect = datetime.strptime

    json_data = [
        {'source': 'SOLAR1', 'time_tag': None, 'bt': '5.0', 'bz_gsm': '2.0'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'bt': None, 'bz_gsm': '2.0'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'bt': '5.0', 'bz_gsm': None},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:55:00', 'bt': '6.0', 'bz_gsm': '3.0'},
    ]
    mean_bt, mean_bz = aurora.processSolarWindMagData(json_data)
    assert mean_bt == 6.0
    assert mean_bz == 3.0


@patch('indi_allsky.aurora.datetime')
def test_processSolarWindPlasmaData_none_fields(mock_datetime, aurora):
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = now
    mock_datetime.strptime.side_effect = datetime.strptime

    json_data = [
        {'source': 'SOLAR1', 'time_tag': None, 'proton_density': '1.0', 'proton_speed': '100.0', 'proton_temperature': '1000'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'proton_density': None, 'proton_speed': '100.0', 'proton_temperature': '1000'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'proton_density': '1.0', 'proton_speed': None, 'proton_temperature': '1000'},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:50:00', 'proton_density': '1.0', 'proton_speed': '100.0', 'proton_temperature': None},
        {'source': 'SOLAR1', 'time_tag': '2023-01-01T11:55:00', 'proton_density': '2.0', 'proton_speed': '200.0', 'proton_temperature': '2000'},
    ]
    density, speed, temp = aurora.processSolarWindPlasmaData(json_data)
    assert density == 2.0
    assert speed == 200.0
    assert temp == 2000


def test_processHemiPowerData_unmatched_lines(aurora):
    text_data = """# Comment line
invalid line that does not match
2023-01-01_12:05 2023-01-01_12:35 18 25
"""
    n_gw, s_gw = aurora.processHemiPowerData(text_data)
    assert n_gw == 18
    assert s_gw == 25


def test_update_ovation_success_and_failures(aurora):
    # 1. Success using cached data
    aurora.ovation_json_data = {'coordinates': [[10, 20, 5]]}
    cam_data = {}
    aurora.update_ovation(cam_data, 20.0, 10.0)
    assert cam_data['OVATION_MAX'] == 5

    # 2. HTTP None error
    aurora.ovation_json_data = None
    with patch.object(aurora, 'download_json', return_value=None):
        with pytest.raises(AuroraDataUpdateFailure, match='HTTP error'):
            aurora.update_ovation(cam_data, 20.0, 10.0)

    # 3. Exceptions during download
    import socket, urllib3, ssl, requests
    exceptions = [
        json.JSONDecodeError("msg", "doc", 0),
        socket.gaierror("dns error"),
        socket.timeout("timed out"),
        requests.exceptions.ConnectTimeout("conn timeout"),
        requests.exceptions.ConnectionError("conn error"),
        requests.exceptions.ReadTimeout("read timeout"),
        urllib3.exceptions.ReadTimeoutError(None, "url", "read timeout"),
        ssl.SSLCertVerificationError("cert fail"),
        requests.exceptions.SSLError("ssl error"),
    ]
    for exc in exceptions:
        with patch.object(aurora, 'download_json', side_effect=exc):
            with pytest.raises(AuroraDataUpdateFailure):
                aurora.update_ovation(cam_data, 20.0, 10.0)


def test_update_kpindex_success_and_failures(aurora):
    # 1. Success using cached data
    aurora.kpindex_json_data = [{'Kp': '2.0'}, {'Kp': '3.0'}]
    cam_data = {}
    aurora.update_kpindex(cam_data)
    assert cam_data['KPINDEX_CURRENT'] == 3.0
    assert 'KPINDEX_COEF' in cam_data

    # 2. None error
    aurora.kpindex_json_data = None
    with patch.object(aurora, 'download_json', return_value=None):
        with pytest.raises(AuroraDataUpdateFailure, match='No kpindex data'):
            aurora.update_kpindex(cam_data)

    # 3. Exceptions
    import socket, urllib3, ssl, requests
    exceptions = [
        json.JSONDecodeError("msg", "doc", 0),
        socket.gaierror("dns"),
        socket.timeout("timeout"),
        requests.exceptions.ConnectTimeout("timeout"),
        requests.exceptions.ConnectionError("conn"),
        urllib3.exceptions.ReadTimeoutError(None, "url", "read timeout"),
        ssl.SSLCertVerificationError("ssl"),
        requests.exceptions.SSLError("ssl"),
    ]
    for exc in exceptions:
        with patch.object(aurora, 'download_json', side_effect=exc):
            with pytest.raises(AuroraDataUpdateFailure):
                aurora.update_kpindex(cam_data)


def test_update_solar_wind_mag_data_success_and_failures(aurora):
    # 1. Success with mock processing
    aurora.solar_wind_mag_json_data = [{'mock': 1}]
    cam_data = {}
    with patch.object(aurora, 'processSolarWindMagData', return_value=(5.555, -2.222)):
        aurora.update_solar_wind_mag_data(cam_data)
        assert cam_data['AURORA_MAG_BT'] == 5.55
        assert cam_data['AURORA_MAG_GSM_BZ'] == -2.22


    # 2. None error
    aurora.solar_wind_mag_json_data = None
    with patch.object(aurora, 'download_json', return_value=None):
        with pytest.raises(AuroraDataUpdateFailure, match='No solar wind data'):
            aurora.update_solar_wind_mag_data(cam_data)

    # 3. Download exceptions
    import socket, urllib3, ssl, requests
    exceptions = [
        json.JSONDecodeError("msg", "doc", 0),
        socket.gaierror("dns"),
        socket.timeout("timeout"),
        requests.exceptions.ConnectTimeout("timeout"),
        requests.exceptions.ConnectionError("conn"),
        urllib3.exceptions.ReadTimeoutError(None, "url", "read timeout"),
        ssl.SSLCertVerificationError("ssl"),
        requests.exceptions.SSLError("ssl"),
    ]
    for exc in exceptions:
        with patch.object(aurora, 'download_json', side_effect=exc):
            with pytest.raises(AuroraDataUpdateFailure):
                aurora.update_solar_wind_mag_data(cam_data)

    # 4. Processing errors
    aurora.solar_wind_mag_json_data = [{'mock': 1}]
    for proc_exc in [ValueError("err"), KeyError("err"), IndexError("err")]:
        with patch.object(aurora, 'processSolarWindMagData', side_effect=proc_exc):
            with pytest.raises(AuroraDataProcessingError):
                aurora.update_solar_wind_mag_data(cam_data)


def test_update_solar_wind_plasma_data_success_and_failures(aurora):
    # 1. Success with mock processing
    aurora.solar_wind_plasma_json_data = [{'mock': 1}]
    cam_data = {}
    with patch.object(aurora, 'processSolarWindPlasmaData', return_value=(3.333, 450.666, 120000)):
        aurora.update_solar_wind_plasma_data(cam_data)
        assert cam_data['AURORA_PLASMA_DENSITY'] == 3.33
        assert cam_data['AURORA_PLASMA_SPEED'] == 450.67
        assert cam_data['AURORA_PLASMA_TEMP'] == 120000

    # 2. None error
    aurora.solar_wind_plasma_json_data = None
    with patch.object(aurora, 'download_json', return_value=None):
        with pytest.raises(AuroraDataUpdateFailure, match='No solar wind plasma data'):
            aurora.update_solar_wind_plasma_data(cam_data)

    # 3. Download exceptions
    import socket, urllib3, ssl, requests
    exceptions = [
        json.JSONDecodeError("msg", "doc", 0),
        socket.gaierror("dns"),
        socket.timeout("timeout"),
        requests.exceptions.ConnectTimeout("timeout"),
        requests.exceptions.ConnectionError("conn"),
        urllib3.exceptions.ReadTimeoutError(None, "url", "read timeout"),
        ssl.SSLCertVerificationError("ssl"),
        requests.exceptions.SSLError("ssl"),
    ]
    for exc in exceptions:
        with patch.object(aurora, 'download_json', side_effect=exc):
            with pytest.raises(AuroraDataUpdateFailure):
                aurora.update_solar_wind_plasma_data(cam_data)

    # 4. Processing errors
    aurora.solar_wind_plasma_json_data = [{'mock': 1}]
    for proc_exc in [ValueError("err"), KeyError("err"), IndexError("err")]:
        with patch.object(aurora, 'processSolarWindPlasmaData', side_effect=proc_exc):
            with pytest.raises(AuroraDataProcessingError):
                aurora.update_solar_wind_plasma_data(cam_data)


def test_update_hemi_power_data_success_and_failures(aurora):
    # 1. Success with mock processing
    aurora.hemi_power_data = "mock power"
    cam_data = {}
    with patch.object(aurora, 'processHemiPowerData', return_value=(15, 25)):
        aurora.update_hemi_power_data(cam_data)
        assert cam_data['AURORA_N_HEMI_GW'] == 15
        assert cam_data['AURORA_S_HEMI_GW'] == 25

    # 2. None error
    aurora.hemi_power_data = None
    with patch.object(aurora, 'download_txt', return_value=None):
        with pytest.raises(AuroraDataUpdateFailure, match='No hemispheric power data'):
            aurora.update_hemi_power_data(cam_data)

    # 3. Download exceptions
    import socket, urllib3, ssl, requests
    exceptions = [
        socket.gaierror("dns"),
        socket.timeout("timeout"),
        requests.exceptions.ConnectTimeout("timeout"),
        requests.exceptions.ConnectionError("conn"),
        urllib3.exceptions.ReadTimeoutError(None, "url", "read timeout"),
        ssl.SSLCertVerificationError("ssl"),
        requests.exceptions.SSLError("ssl"),
    ]
    for exc in exceptions:
        with patch.object(aurora, 'download_txt', side_effect=exc):
            with pytest.raises(AuroraDataUpdateFailure):
                aurora.update_hemi_power_data(cam_data)

    # 4. Processing errors
    aurora.hemi_power_data = "mock power"
    for proc_exc in [IndexError("err"), KeyError("err"), ValueError("err")]:
        with patch.object(aurora, 'processHemiPowerData', side_effect=proc_exc):
            with pytest.raises(AuroraDataProcessingError):
                aurora.update_hemi_power_data(cam_data)


def test_update_camera_full_success_and_failures(flask_app, aurora):
    with flask_app.app_context():
        from indi_allsky.flask.models import IndiAllSkyDbCameraTable
        from indi_allsky.flask import db

        camera = IndiAllSkyDbCameraTable.query.first()
        if not camera:
            camera = IndiAllSkyDbCameraTable(
                name='Aurora Test Cam',
                uuid='cam-aurora-1',
                latitude=64.0,
                longitude=-21.0,
                elevation=10,
                nightSunAlt=-6.0,
            )
            db.session.add(camera)
            db.session.commit()

        # 1. Update full success with camera.data is None
        camera.data = None
        with patch.object(aurora, 'update_ovation'), \
             patch.object(aurora, 'update_kpindex'), \
             patch.object(aurora, 'update_solar_wind_mag_data'), \
             patch.object(aurora, 'update_solar_wind_plasma_data'), \
             patch.object(aurora, 'update_hemi_power_data'):

            aurora.update(camera)
            assert camera.data is not None
            assert 'AURORA_DATA_TS' in camera.data

        # 2. Update full success with existing camera.data
        camera.data = {'existing_key': 123}
        with patch.object(aurora, 'update_ovation'), \
             patch.object(aurora, 'update_kpindex'), \
             patch.object(aurora, 'update_solar_wind_mag_data'), \
             patch.object(aurora, 'update_solar_wind_plasma_data'), \
             patch.object(aurora, 'update_hemi_power_data'):

            aurora.update(camera)
            assert camera.data['existing_key'] == 123
            assert 'AURORA_DATA_TS' in camera.data

        # 3. Update failures gracefully caught
        camera.data = {'existing_key': 456}
        with patch.object(aurora, 'update_ovation', side_effect=AuroraDataUpdateFailure()), \
             patch.object(aurora, 'update_kpindex', side_effect=AuroraDataProcessingError()), \
             patch.object(aurora, 'update_solar_wind_mag_data', side_effect=AuroraDataUpdateFailure()), \
             patch.object(aurora, 'update_solar_wind_plasma_data', side_effect=AuroraDataProcessingError()), \
             patch.object(aurora, 'update_hemi_power_data', side_effect=AuroraDataUpdateFailure()):

            aurora.update(camera)
            # When none succeed, camera_update is False, so AURORA_DATA_TS is not added
            assert 'AURORA_DATA_TS' not in camera.data

        # 4. Alternative exceptions
        with patch.object(aurora, 'update_ovation', side_effect=AuroraDataProcessingError()), \
             patch.object(aurora, 'update_kpindex', side_effect=AuroraDataUpdateFailure()), \
             patch.object(aurora, 'update_solar_wind_mag_data', side_effect=AuroraDataProcessingError()), \
             patch.object(aurora, 'update_solar_wind_plasma_data', side_effect=AuroraDataUpdateFailure()), \
             patch.object(aurora, 'update_hemi_power_data', side_effect=AuroraDataProcessingError()):

            aurora.update(camera)
            assert 'AURORA_DATA_TS' not in camera.data


