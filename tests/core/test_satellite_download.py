import pytest
import socket
from unittest.mock import patch, MagicMock

from indi_allsky.satellite_download import IndiAllskyUpdateSatelliteData
from indi_allsky.flask.models import IndiAllSkyDbTleDataTable
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
    """Ensure TLE table is clean before and after each test."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTleDataTable).delete()
        db.session.commit()
    yield
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbTleDataTable).delete()
        db.session.commit()


def test_init_stores_config(flask_app):
    """__init__ stores config correctly"""
    config = {'test_key': 'test_value'}
    updater = IndiAllskyUpdateSatelliteData(config)
    assert updater.config == config
    assert updater._miscDb is not None


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
    mock_get.assert_called_once_with(
        "http://example.com/tle",
        allow_redirects=True,
        verify=True,
        timeout=(15.0, 30.0),
    )


@patch('indi_allsky.satellite_download.requests.get')
def test_download_tle_http_error(mock_get, flask_app):
    """download_tle - HTTP error returns None"""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    result = updater.download_tle("http://example.com/tle")

    assert result is None


def test_import_entries_valid(flask_app, db):
    """import_entries - valid TLE data creates DB entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    updater.import_entries(group, VALID_TLE)

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 1
    assert entries[0].title == "ISS (ZARYA)"
    assert entries[0].line1.startswith("1 25544U")
    assert entries[0].line2.startswith("2 25544")


def test_import_entries_multiple(flask_app, db):
    """import_entries - multiple TLE entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_STARLINK

    updater.import_entries(group, MULTI_TLE)

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 2


def test_import_entries_invalid_title(flask_app, db):
    """import_entries - title > 24 chars triggers assertion and rollback"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    # Title > 24 chars
    bad_title = "A" * 25
    invalid_tle = f"{bad_title}\n{VALID_LINE1}\n{VALID_LINE2}\n"

    # The assertion `assert len(title) <= 24` will fail,
    # caught by `except AssertionError:` → calls rollback and returns.
    updater.import_entries(group, invalid_tle)

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0


def test_import_entries_incomplete_data(flask_app, db):
    """import_entries - incomplete TLE data (2 lines instead of 3) triggers rollback"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_VISUAL

    # Only 2 lines — missing line2, so StopIteration triggers rollback
    incomplete_tle = f"ISS (ZARYA)\n{VALID_LINE1}\n"

    updater.import_entries(group, incomplete_tle)

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0


@patch('indi_allsky.satellite_download.requests.get')
def test_update_success(mock_get, flask_app, db):
    """update - successful flow: downloads, deletes old, imports new"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = VALID_TLE
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    updater.update()

    for group in [constants.SATELLITE_VISUAL, constants.SATELLITE_STARLINK, constants.SATELLITE_STATIONS]:
        entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
        assert len(entries) == 1


@patch('indi_allsky.satellite_download.requests.get')
def test_update_network_error_continues(mock_get, flask_app, db):
    """update - network error on one group continues to next"""
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call (VISUAL) raises network error
            raise socket.gaierror("Name resolution error")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = VALID_TLE
        return mock_resp

    mock_get.side_effect = side_effect

    updater = IndiAllskyUpdateSatelliteData({})
    updater.update()

    # First group failed, so no entries
    visual_entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(
        group=constants.SATELLITE_VISUAL
    ).all()
    assert len(visual_entries) == 0

    # Other groups should have entries
    starlink_entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(
        group=constants.SATELLITE_STARLINK
    ).all()
    assert len(starlink_entries) == 1


@patch('indi_allsky.satellite_download.requests.get')
def test_update_download_none(mock_get, flask_app, db):
    """update - download returns None (HTTP error) skips import"""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_get.return_value = mock_resp

    updater = IndiAllskyUpdateSatelliteData({})
    updater.update()

    for group in [constants.SATELLITE_VISUAL, constants.SATELLITE_STARLINK, constants.SATELLITE_STATIONS]:
        entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
        assert len(entries) == 0


def test_import_entries_empty(flask_app, db):
    """import_entries - empty input produces no entries"""
    updater = IndiAllskyUpdateSatelliteData({})
    group = constants.SATELLITE_STATIONS

    updater.import_entries(group, "")

    entries = db.session.query(IndiAllSkyDbTleDataTable).filter_by(group=group).all()
    assert len(entries) == 0
