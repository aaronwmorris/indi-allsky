import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbVideoTable,
)
from indi_allsky.flask.views import (
    _visible_asi676mc_cameras,
    _can_save_standard_configuration,
    _asi676mc_feature_enabled,
    _calibration_owner,
    _calibration_save_actor,
    _camera_identity,
    _supported_asi676mc_camera,
    asi676mc_calibration_required,
    JsonLatestImageView,
)
from werkzeug.exceptions import Forbidden, NotFound


@pytest.fixture
def view_db(flask_app):
    """Seed DB for views testing."""
    with flask_app.app_context():
        # Clear existing tables
        db.session.query(IndiAllSkyDbImageTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="ZWO ASI676MC",
            uuid="12345678-1234-1234-1234-123456789012",
            latitude=-34.9285,
            longitude=138.6007,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
            hidden=False,
            az=180.0,
            utc_offset=36000.0,
            lensFocalLength=4.0,
            lensFocalRatio=2.0,
            lensImageCircle=180.0,
            cfa=None,
            owner="Admin",
            width=1920,
            height=1080,
            pixelSize=2.4,
            data={
                'vs_image_circle_diameter': 3500,
                'vs_latitude_offset': 0.0,
                'vs_longitude_offset': 0.0,
                'vs_offset_x': 0.0,
                'vs_offset_y': 0.0,
                'vs_magnitude': 6.0,
                'vs_constellations': True,
                'vs_constellationlabels': False,
                'vs_showstars': True,
                'vs_showstarlabels': True,
                'vs_showplanets': True,
                'vs_showplanetlabels': True,
            },
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FOLDER': '/tmp',
                'CCD_EXPOSURE_MAX': 15.0,
                'FOCUS_MODE': False,
            },
            level="1.0",
            note='test',
        )
        db.session.add(config_entry)

        admin = IndiAllSkyDbUserTable(
            username="admin_user",
            password="hashed_password",
            email="admin@example.org",
            name="Admin",
            active=True,
            admin=True,
        )
        db.session.add(admin)

        non_admin = IndiAllSkyDbUserTable(
            username="user_user",
            password="hashed_password",
            email="user@example.org",
            name="User",
            active=True,
            admin=False,
        )
        db.session.add(non_admin)

        db.session.commit()
        yield
        db.session.remove()


def test_helper_functions_and_decorators(flask_app, view_db):
    with flask_app.app_context():
        # Test _camera_identity
        cam = IndiAllSkyDbCameraTable.query.get(1)
        ident = _camera_identity(cam)
        assert ident['id'] == 1
        assert ident['uuid'] == cam.uuid

        # Test _supported_asi676mc_camera
        assert _supported_asi676mc_camera("invalid") is None
        assert _supported_asi676mc_camera(999) is None

        with patch("indi_allsky.asi676mc.camera_record_matches", return_value=True):
            supported = _supported_asi676mc_camera(1)
            assert supported is not None

        # Test _visible_asi676mc_cameras
        with patch("indi_allsky.asi676mc.camera_record_matches", return_value=True):
            visible = _visible_asi676mc_cameras()
            assert len(visible) >= 1

        # Test _can_save_standard_configuration
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            assert _can_save_standard_configuration() is True

        with patch.dict(flask_app.config, {'LOGIN_DISABLED': False}):
            with patch("indi_allsky.flask.views.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.is_admin = True
                assert _can_save_standard_configuration() is True

                mock_user.is_admin = False
                assert _can_save_standard_configuration() is False

        # Test _calibration_owner and _calibration_save_actor
        with patch("indi_allsky.flask.views.current_user") as mock_user:
            mock_user.is_authenticated = True
            mock_user.username = "test_user"
            assert _calibration_owner() == "user:test_user"
            assert _calibration_save_actor() == "test_user"

            mock_user.is_authenticated = False
            with flask_app.test_request_context('/'):
                from flask import session
                owner = _calibration_owner()
                assert owner.startswith("browser:")
                assert _calibration_save_actor() == "system"

        # Test asi676mc_calibration_required decorator
        @asi676mc_calibration_required
        def dummy_func():
            return "ok"

        with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=False):
            with pytest.raises(Forbidden):
                dummy_func()

        with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True):
            with patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=False):
                with pytest.raises(NotFound):
                    dummy_func()

            with patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True):
                with patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[]):
                    with pytest.raises(NotFound):
                        dummy_func()

                with patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[cam]):
                    assert dummy_func() == "ok"


def test_ajax_status_update_view(flask_app, view_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/ajax/status_update?camera_id=1')
    assert res.status_code == 200
    json_data = res.get_json()
    assert 'status_text' in json_data


def test_index_canvas_view(flask_app, view_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/?camera_id=1')
    assert res.status_code == 200


def test_index_img_view(flask_app, view_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/index_img?camera_id=1')
    assert res.status_code == 200


def test_virtual_sky_view(flask_app, view_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/virtualsky?camera_id=1&timestamp=123456789')
    assert res.status_code == 200


def test_realtime_keogram_view(flask_app, view_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/realtime_keogram?camera_id=1')
    assert res.status_code == 200


def test_json_latest_image_view_branches(flask_app, view_db):
    client = flask_app.test_client()

    # 1. Limit clamping > 86400
    res = client.get('/indi-allsky/js/latest?camera_id=1&limit_s=90000')
    assert res.status_code == 200

    # 2. Focus mode enabled branch
    with patch("indi_allsky.flask.views.JsonLatestImageView.cameraSetup") as mock_setup:
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': True, 'IMAGE_FILE_TYPE': 'jpg', 'IMAGE_FOLDER': '/tmp'}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        view.capture_pause = False

        # Create temporary file to simulate latest.jpg
        temp_img = Path('/tmp/latest.jpg')
        temp_img.touch()
        try:
            with flask_app.test_request_context('/js/latest_image_view?camera_id=1&limit_s=900'):
                data = view.get_objects()
                assert data['latest_image']['url'] is not None
        finally:
            if temp_img.exists():
                temp_img.unlink()

    # 3. Capture pause branch
    with flask_app.test_request_context('/js/latest?camera_id=1'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': False}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        with patch.object(view, 'cameraSetup'):
            view.capture_pause = True
            data = view.get_objects()
            assert data['latest_image']['message'] == 'Capture paused'

    # 4. Daytime branches (night=0)
    with flask_app.test_request_context('/js/latest?camera_id=1&night=0'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': False, 'IMAGE_FILE_TYPE': 'jpg', 'IMAGE_FOLDER': '/tmp'}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        view.capture_pause = False
        view.local_indi_allsky = False
        view.daytime_capture = True
        view.daytime_capture_save = False
        view.sun_set_date = datetime.now() + timedelta(hours=2)

        with patch.object(view, 'cameraSetup'):
            data = view.get_objects()
            assert 'Night starts in' in data['latest_image']['message']

            view.sun_set_date = None
            data = view.get_objects()
            assert 'Sun never sets' in data['latest_image']['message']


def test_json_latest_image_view_get_latest_image(flask_app, view_db):
    with flask_app.app_context():
        view = JsonLatestImageView()
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        view.s3_prefix = ''

        # Seed an image
        img = IndiAllSkyDbImageTable(
            camera_id=1,
            filename='test.jpg',
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=1000.0,
            width=1920,
            height=1080,
            night=True,
        )
        db.session.add(img)
        db.session.commit()

        # Test getLatestImage success
        data = view.getLatestImage(1, 900)
        assert data['url'] is not None

        # Test error handling when getUrl raises ValueError
        with patch.object(IndiAllSkyDbImageTable, 'getUrl', side_effect=ValueError("bad path")):
            data_err = view.getLatestImage(1, 900)
            assert data_err['url'] is None

def test_asi676mc_feature_enabled_helper(flask_app, view_db):
    with flask_app.app_context():
        with patch("indi_allsky.config.IndiAllSkyConfig") as mock_cfg_class:
            mock_cfg_inst = MagicMock()
            mock_cfg_inst.config = {}
            mock_cfg_class.return_value = mock_cfg_inst
            with patch("indi_allsky.asi676mc.feature_enabled", return_value=True):
                assert _asi676mc_feature_enabled() is True


def test_json_latest_image_view_more_branches(flask_app, view_db):
    # 1. web_nonlocal_images no_image_message extra text
    with flask_app.test_request_context('/js/latest?camera_id=1'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': False}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = True
        view.capture_pause = False
        with patch.object(view, 'cameraSetup'):
            with patch.object(view, 'getLatestImage', return_value={'url': None}):
                data = view.get_objects()
                assert '(Non-local images enabled)' in data['latest_image']['message']

    # 2. Focus mode image missing / outdated
    with flask_app.test_request_context('/js/latest?camera_id=1'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': True, 'IMAGE_FILE_TYPE': 'jpg', 'IMAGE_FOLDER': '/tmp/nonexistent_folder_xyz'}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        view.capture_pause = False
        with patch.object(view, 'cameraSetup'):
            with patch.object(view, 'getLatestImage', return_value={'url': None}):
                data = view.get_objects()
                assert data['latest_image']['url'] is None

    # 3. Daytime capture with non-local images verify_admin_network fail
    with flask_app.test_request_context('/js/latest?camera_id=1&night=0'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': False, 'IMAGE_FILE_TYPE': 'jpg', 'IMAGE_FOLDER': '/tmp'}
        view.camera_now = datetime.now()
        view.sun_set_date = datetime.now() + timedelta(hours=1)
        view.web_nonlocal_images = True
        view.capture_pause = False
        view.daytime_capture = True
        view.daytime_capture_save = False
        view.local_indi_allsky = False
        with patch.object(view, 'cameraSetup'):
            with patch.object(view, 'verify_admin_network', return_value=False):
                data = view.get_objects()
                assert data['latest_image']['url'] is None

    # 4. Daytime capture file existing, current vs outdated
    temp_dir = tempfile.TemporaryDirectory()
    try:
        image_p = Path(temp_dir.name).joinpath('latest.jpg')
        image_p.touch()

        with flask_app.test_request_context('/js/latest?camera_id=1&night=0'):
            view = JsonLatestImageView()
            view.indi_allsky_config = {'FOCUS_MODE': False, 'IMAGE_FILE_TYPE': 'jpg', 'IMAGE_FOLDER': temp_dir.name}
            view.camera_now = datetime.now()
            view.sun_set_date = datetime.now() + timedelta(hours=1)
            view.web_nonlocal_images = False
            view.capture_pause = False
            view.daytime_capture = True
            view.daytime_capture_save = False
            view.local_indi_allsky = True
            with patch.object(view, 'cameraSetup'):
                data = view.get_objects()
                assert data['latest_image']['url'] is not None
                assert data['latest_image']['message'] == ''

                # Test outdated image
                view.camera_now = datetime.now() + timedelta(hours=5)
                data_outdated = view.get_objects()
                assert data_outdated['latest_image']['message'] == 'Image is out of date'
    finally:
        temp_dir.cleanup()

    # 5. Database image URL population
    with flask_app.test_request_context('/js/latest?camera_id=1'):
        view = JsonLatestImageView()
        view.indi_allsky_config = {'FOCUS_MODE': False}
        view.camera_now = datetime.now()
        view.web_nonlocal_images = False
        view.capture_pause = False
        with patch.object(view, 'cameraSetup'):
            with patch.object(view, 'getLatestImage', return_value={'url': '/static/test.jpg', 'width': 1920, 'height': 1080}):
                data = view.get_objects()
                assert data['latest_image']['url'] == '/static/test.jpg'
                assert data['latest_image']['message'] == ''


def test_redirects_fallback_camera(flask_app, view_db):
    with flask_app.app_context():
        img = IndiAllSkyDbImageTable(
            id=100,
            camera_id=1,
            filename="fallback_img.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=1000.0,
            width=1920,
            height=1080,
            night=True,
        )
        vid = IndiAllSkyDbVideoTable(
            id=100,
            camera_id=1,
            filename="fallback_vid.mp4",
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(img)
        db.session.add(vid)
        db.session.commit()

    client = flask_app.test_client()

    with patch("indi_allsky.flask.views.BaseView.getLatestCamera") as mock_get_cam:
        with flask_app.app_context():
            cam = db.session.get(IndiAllSkyDbCameraTable, 1)
            mock_get_cam.return_value = cam

        with patch.object(IndiAllSkyDbImageTable, 'getUrl', return_value='/static/image1.jpg'):
            res = client.get('/indi-allsky/latestimage')
            assert res.status_code == 302

        with patch.object(IndiAllSkyDbVideoTable, 'getUrl', return_value='/static/video1.mp4'):
            res_v = client.get('/indi-allsky/latesttimelapse')
            assert res_v.status_code == 302

        res_iv = client.get('/indi-allsky/latestimageview')
        assert res_iv.status_code == 302

        res_vw = client.get('/indi-allsky/latesttimelapsewatch')
        assert res_vw.status_code == 302

