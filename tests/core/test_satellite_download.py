import time
import socket
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from indi_allsky.satellite_download import IndiAllskyUpdateSatelliteData
from indi_allsky.flask.models import (
    IndiAllSkyDbTleDataTable,
    IndiAllSkyDbNotificationTable,
    NotificationCategory,
)
from indi_allsky import constants


# Sample Valid TLE — title must be <= 24 chars, lines 1 and 2 must be exactly 69 chars
VALID_TITLE = "ISS (ZARYA)             "  # 24 chars exactly
VALID_LINE1 = "1 25544U 98067A   21264.51782528  .00002893  00000-0  60680-4 0  9998"  # 69 chars
VALID_LINE2 = "2 25544  51.6449 208.5765 0001327  66.2683  48.1373 15.48919755303825"  # 69 chars

VALID_TLE = f"{VALID_TITLE}\n{VALID_LINE1}\n{VALID_LINE2}\n"

MULTI_TLE = (
    f"{VALID_TITLE}\n{VALID_LINE1}\n{VALID_LINE2}\n"
    f"NOAA 15                 \n{VALID_LINE1}\n{VALID_LINE2}\n"
)


@pytest.fixture(autouse=True)
def clean_tle_table(flask_app, db):
    """Ensure TLE and notification tables are clean before and after each test."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTleDataTable).delete()
        db.session.query(IndiAllSkyDbNotificationTable).delete()
        db.session.commit()
    yield
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTleDataTable).delete()
        db.session.query(IndiAllSkyDbNotificationTable).delete()
        db.session.commit()


def test_init_stores_config(flask_app):
    """__init__ stores config and configures visual-only group"""
    config = {'test_key': 'test_value'}
    updater = IndiAllskyUpdateSatelliteData(config)
    assert updater.config == config
    assert updater._miscDb is not None
    assert list(updater.tle_urls.keys()) == [constants.SATELLITE_VISUAL]


@patch('indi_allsky.satellite_download.requests.get')
def test_download_tle_success(mock_get, flask_app):
    """download_tle - success returns text"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_TLE
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    result = updater.download_tle("http://example.com/tle")

    assert result == VALID_TLE
    assert updater.last_status_code == 200
    mock_get.assert_called_once_with(
        "http://example.com/tle",
        allow_redirects=True,
        verify=True,
        timeout=(15.0, 30.0),
    )


@patch('indi_allsky.satellite_download.requests.get')
def test_download_tle_http_error(mock_get, flask_app):
    """download_tle - HTTP error returns None and records status code"""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    result = updater.download_tle("http://example.com/tle")

    assert result is None
    assert updater.last_status_code == 404


def test_import_entries_valid(flask_app, db):
    """import_entries - valid TLE data creates DB entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    count = updater.import_entries(group, VALID_TLE)
    assert count == 1

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 1
    assert entries[0].title == "ISS (ZARYA)"
    assert entries[0].line1.startswith("1 25544U")
    assert entries[0].line2.startswith("2 25544")


def test_import_entries_multiple(flask_app, db):
    """import_entries - multiple TLE entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    count = updater.import_entries(group, MULTI_TLE)
    assert count == 2

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 2


def test_import_entries_invalid_title(flask_app, db):
    """import_entries - title > 24 chars triggers assertion and rollback"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    bad_title = "A" * 25
    invalid_tle = f"{bad_title}\n{VALID_LINE1}\n{VALID_LINE2}\n"

    result = updater.import_entries(group, invalid_tle)
    assert result is None

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0


def test_import_entries_incomplete_data(flask_app, db):
    """import_entries - incomplete TLE data triggers rollback"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    incomplete_tle = f"ISS (ZARYA)\n{VALID_LINE1}\n"

    result = updater.import_entries(group, incomplete_tle)
    assert result is None

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0


def test_import_entries_empty(flask_app, db):
    """import_entries - empty input produces no entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    count = updater.import_entries(group, "")
    assert count == 0

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0


@patch('indi_allsky.satellite_download.requests.get')
def test_update_success(mock_get, flask_app, db):
    """update - successful flow: downloads visual only, updates timestamp, resets fail count"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_TLE
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    success = updater.update(force=True)

    assert success is True
    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=constants.SATELLITE_VISUAL).all()
    assert len(entries) == 1

    last_ts = int(updater._miscDb.getState('SATELLITE_TLE_TS'))
    assert last_ts > 0
    fail_count = int(updater._miscDb.getState('SATELLITE_TLE_FAIL_COUNT'))
    assert fail_count == 0


@patch('indi_allsky.satellite_download.requests.get')
def test_update_freshness_skip(mock_get, flask_app):
    """update - skips download if cached data is less than 24 hours old"""
    updater = IndiAllskyUpdateSatelliteData({})
    now = int(time.time())
    updater._miscDb.setState('SATELLITE_TLE_TS', now - 43200)  # 12 hours old

    success = updater.update(force=False)
    assert success is True
    mock_get.assert_not_called()


@patch('indi_allsky.satellite_download.requests.get')
def test_update_cooldown_active_skip(mock_get, flask_app):
    """update - skips download if cooldown is active"""
    updater = IndiAllskyUpdateSatelliteData({})
    now = int(time.time())
    updater._miscDb.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', now + 3600)  # in cooldown for 1 hour

    success = updater.update(force=False)
    assert success is False
    mock_get.assert_not_called()


@patch('indi_allsky.satellite_download.requests.get')
def test_update_rate_limit_backoff(mock_get, flask_app, db):
    """update - HTTP 403 / 429 sets exponential cooldown (starts at 2 hours) and creates notification"""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})

    # First rate-limit hit: 2 hours delay
    now = time.time()
    success = updater.update(force=True)
    assert success is False

    fail_count = int(updater._miscDb.getState('SATELLITE_TLE_FAIL_COUNT'))
    assert fail_count == 1
    next_ts = int(updater._miscDb.getState('SATELLITE_TLE_NEXT_ATTEMPT_TS'))
    assert next_ts >= int(now + 7100)

    # Verify notification created
    notices = db.session.query(IndiAllSkyDbNotificationTable).filter_by(
        item='satellite_tle_error',
        category=NotificationCategory.GENERAL,
    ).all()
    assert len(notices) == 1
    assert 'rate limit reached' in notices[0].notification

    # Second rate-limit hit: exponential increase to 4 hours delay
    now2 = time.time()
    success2 = updater.update(force=True)
    assert success2 is False

    fail_count2 = int(updater._miscDb.getState('SATELLITE_TLE_FAIL_COUNT'))
    assert fail_count2 == 2
    next_ts2 = int(updater._miscDb.getState('SATELLITE_TLE_NEXT_ATTEMPT_TS'))
    assert next_ts2 >= int(now2 + 14300)


@patch('indi_allsky.satellite_download.requests.get')
def test_update_network_error_backoff(mock_get, flask_app, db):
    """update - network error sets exponential cooldown (starts at 15 minutes) and creates notification"""
    mock_get.side_effect = socket.gaierror("DNS failed")

    updater = IndiAllskyUpdateSatelliteData({})
    now = time.time()
    success = updater.update(force=True)
    assert success is False

    fail_count = int(updater._miscDb.getState('SATELLITE_TLE_FAIL_COUNT'))
    assert fail_count == 1
    next_ts = int(updater._miscDb.getState('SATELLITE_TLE_NEXT_ATTEMPT_TS'))
    assert next_ts >= int(now + 890)

    notices = db.session.query(IndiAllSkyDbNotificationTable).filter_by(
        item='satellite_tle_error',
        category=NotificationCategory.GENERAL,
    ).all()
    assert len(notices) == 1
    assert 'DNS resolution error' in notices[0].notification


@patch('indi_allsky.satellite_download.requests.get')
def test_update_clears_notification_on_success(mock_get, flask_app, db):
    """update - success clears previous error notification and resets fail count"""
    updater = IndiAllskyUpdateSatelliteData({})

    # Manually seed failure state and notification
    updater._miscDb.setState('SATELLITE_TLE_FAIL_COUNT', 3)
    updater._miscDb.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', int(time.time()) + 3600)
    updater._miscDb.addNotification(
        NotificationCategory.GENERAL,
        'satellite_tle_error',
        'Previous failure',
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_TLE
    mock_get.return_value = mock_resp

    success = updater.update(force=True)
    assert success is True

    # Assert notification was cleared
    now = datetime.now()
    active_notices = db.session.query(IndiAllSkyDbNotificationTable).filter(
        IndiAllSkyDbNotificationTable.item == 'satellite_tle_error',
        IndiAllSkyDbNotificationTable.expireDate > now,
        IndiAllSkyDbNotificationTable.ack == False,
    ).all()
    assert len(active_notices) == 0

    assert int(updater._miscDb.getState('SATELLITE_TLE_FAIL_COUNT')) == 0
    assert int(updater._miscDb.getState('SATELLITE_TLE_NEXT_ATTEMPT_TS')) == 0


@patch('indi_allsky.satellite_download.requests.get')
def test_update_purges_legacy_groups(mock_get, flask_app, db):
    """update - purges legacy groups (e.g. Starlink and Stations) from the DB"""
    # Seed legacy Starlink and Stations records
    legacy_starlink = IndiAllSkyDbTleDataTable(
        title="STARLINK-1234",
        line1=VALID_LINE1,
        line2=VALID_LINE2,
        group=constants.SATELLITE_STARLINK,
    )
    legacy_stations = IndiAllSkyDbTleDataTable(
        title="TIANGONG",
        line1=VALID_LINE1,
        line2=VALID_LINE2,
        group=constants.SATELLITE_STATIONS,
    )
    db.session.add(legacy_starlink)
    db.session.add(legacy_stations)
    db.session.commit()

    assert db.session.query(IndiAllSkyDbTleDataTable).count() == 2

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_TLE
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    success = updater.update(force=True)
    assert success is True

    # Legacy records must be gone, only 1 visual record present
    all_entries = db.session.query(IndiAllSkyDbTleDataTable).all()
    assert len(all_entries) == 1
    assert all_entries[0].group == constants.SATELLITE_VISUAL


def test_allsky_sat_task_scheduling_fresh(flask_app, tmp_path):
    """IndiAllSky startup schedules sat task 3 days out when TLE data is fresh"""
    from indi_allsky.allsky import IndiAllSky
    from indi_allsky.flask.miscDb import miscDb

    mock_config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'LOCATION_ELEVATION': 50,
        'IMAGE_FOLDER': str(tmp_path),
        'VARLIB_FOLDER': str(tmp_path),
        'UPLOAD_WORKERS': 1,
    }

    misc_db = miscDb(mock_config)
    now = int(time.time())
    misc_db.setState('SATELLITE_TLE_TS', now - 3600)  # 1 hour ago
    misc_db.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', 0)

    with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
        mock_cfg_inst = MagicMock()
        mock_cfg_inst.config = mock_config
        mock_cfg_inst.config_id = 1
        mock_cfg_inst.config_level = 1
        mock_cfg_cls.return_value = mock_cfg_inst

        with patch('indi_allsky.allsky.__config_level__', 1):
            allsky = IndiAllSky()
            # Must be scheduled for last_ts + 259200
            expected = (now - 3600) + allsky.sat_data_tasks_offset
            assert abs(allsky.sat_data_tasks_time - expected) < 5


def test_allsky_sat_task_scheduling_cooldown(flask_app, tmp_path):
    """IndiAllSky startup schedules sat task at cooldown timestamp if active"""
    from indi_allsky.allsky import IndiAllSky
    from indi_allsky.flask.miscDb import miscDb

    mock_config = {
        'LOCATION_LATITUDE': -34.9285,
        'LOCATION_LONGITUDE': 138.6007,
        'LOCATION_ELEVATION': 50,
        'IMAGE_FOLDER': str(tmp_path),
        'VARLIB_FOLDER': str(tmp_path),
        'UPLOAD_WORKERS': 1,
    }

    misc_db = miscDb(mock_config)
    now = int(time.time())
    cooldown_target = now + 7200
    misc_db.setState('SATELLITE_TLE_NEXT_ATTEMPT_TS', cooldown_target)

    with patch('indi_allsky.allsky.IndiAllSkyConfig') as mock_cfg_cls:
        mock_cfg_inst = MagicMock()
        mock_cfg_inst.config = mock_config
        mock_cfg_inst.config_id = 1
        mock_cfg_inst.config_level = 1
        mock_cfg_cls.return_value = mock_cfg_inst

        with patch('indi_allsky.allsky.__config_level__', 1):
            allsky = IndiAllSky()
            assert allsky.sat_data_tasks_time == cooldown_target

