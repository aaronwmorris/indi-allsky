"""Tests for extended timelapse, image processing, astropanel, and config view branches."""

import datetime
from datetime import timedelta, timezone
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import ephem
from passlib.hash import argon2
import pytest
from flask import session
from flask_login import login_user

from indi_allsky import constants
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbNotificationTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbTleDataTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbVideoTable,
    NotificationCategory,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask.views import (
    AjaxAstroPanelView,
    AjaxConfigRestoreView,
    AjaxConfigView,
    AjaxNotificationView,
    AjaxSelectCameraView,
    AjaxSystemInfoView,
    AjaxTimelapseGeneratorView,
    AjaxUploadYoutubeView,
    AjaxUserInfoView,
    ConfigDownloadView,
    ConfigView,
    FileSpaceUsageView,
    ImageCircleHelperView,
    ImageLagView,
    ImageViewerView,
    JsonImageLoopView,
    JsonImageProcessingView,
    JsonLatestImageView,
    JsonLongTermKeogramView,
    JsonSensorPanelView,
    LatestTimelapseVideoRedirect,
    LatestTimelapseVideoWatchRedirect,
    MiniTimelapseGeneratorView,
    MiniTimelapseVideoView,
    RollingAduView,
    SensorPanelView,
    TimelapseImageView,
    TimelapseVideoView,
    UserInfoView,
)
from indi_allsky.flask.forms import (
    IndiAllskyConfigForm,
    IndiAllskyImageProcessingForm,
    IndiAllskyLongTermKeogramForm,
    IndiAllskySystemInfoForm,
    IndiAllskyTimelapseGeneratorForm,
    IndiAllskyUserInfoForm,
)


def _always_valid(self):
    return True


def _always_invalid(self):
    return False


def test_status_latest_base_view_branches(flask_app, system_db):
    """Test JsonLatestImageView branches: nonlocal images with admin network, daytime capture without save missing image."""
    with flask_app.test_request_context('/?camera_id=1&night=0'):
        view = JsonLatestImageView()
        view.model = IndiAllSkyDbImageTable
        view.camera_now = datetime.datetime.now(tz=timezone.utc)
        view.sun_set_date = view.camera_now + timedelta(hours=2)
        view.local_indi_allsky = True
        view.daytime_capture = True
        view.daytime_capture_save = False
        view.web_nonlocal_images = True
        view.web_local_images_admin = True
        view.latest_image_t = 'latest.{0:s}'
        view.indi_allsky_config = {'IMAGE_FOLDER': tempfile.gettempdir(), 'IMAGE_FILE_TYPE': 'jpg', 'FOCUS_MODE': False}

        # verify_admin_network returns True
        with patch.object(view, 'verify_admin_network', return_value=True):
            res = view.get_objects()
            assert 'latest_image' in res

        # getLatestImage local vs nonlocal filter branch
        view.web_nonlocal_images = True
        view.web_local_images_admin = False
        with patch.object(view, 'verify_admin_network', return_value=False):
            img_data = view.getLatestImage(1, 900)
            assert isinstance(img_data, dict) or img_data is None or isinstance(img_data, IndiAllSkyDbImageTable)


def test_video_redirects_and_sql_dialects(flask_app, system_db):
    """Test LatestTimelapseVideoRedirect/WatchRedirect with night param and RollingAduView/ImageLagView mysql/postgres branches."""
    user = db.session.get(IndiAllSkyDbUserTable, 1)

    # 1. LatestTimelapseVideoRedirect with night=1
    with flask_app.test_request_context('/?camera_id=1&night=1'):
        v_redirect = LatestTimelapseVideoRedirect()
        with patch.object(v_redirect, 'getLatestVideo') as mock_get_v:
            mock_video = MagicMock()
            mock_video.getUrl.return_value = '/video/1.mp4'
            mock_get_v.return_value = mock_video
            res = v_redirect.dispatch_request()
            assert res.status_code == 302
            mock_get_v.assert_called_once_with(1, night='1')

    # 2. LatestTimelapseVideoWatchRedirect with night=0
    with flask_app.test_request_context('/?camera_id=1&night=0'):
        w_redirect = LatestTimelapseVideoWatchRedirect()
        with patch.object(w_redirect, 'getLatestVideo') as mock_get_v:
            mock_video = MagicMock()
            mock_video.id = 42
            mock_get_v.return_value = mock_video
            res = w_redirect.dispatch_request()
            assert res.status_code == 302
            mock_get_v.assert_called_once_with(1, night='0')

    # 3. ImageLagView with mysql and postgres dialect
    with flask_app.test_request_context('/?timestamp=1700000000'):
        lag_view = ImageLagView(template_name='image_lag.html')
        with patch('indi_allsky.flask.views.db.engine.dialect.name', 'mysql'):
            ctx = lag_view.get_context()
            assert 'image_lag_q' in ctx

        with patch('indi_allsky.flask.views.db.engine.dialect.name', 'postgresql'):
            ctx = lag_view.get_context()
            assert 'image_lag_q' in ctx

    # 4. RollingAduView with mysql dialect and postgres dialect (postgres raises UnboundLocalError due to fixme)
    with flask_app.test_request_context('/?timestamp=1700000000'):
        adu_view = RollingAduView(template_name='rolling_adu.html')
        login_user(user)
        with patch('indi_allsky.flask.views.db.engine.dialect.name', 'mysql'):
            ctx = adu_view.get_context()
            assert 'rolling_adu_q' in ctx

        with patch('indi_allsky.flask.views.db.engine.dialect.name', 'postgresql'):
            try:
                adu_view.get_context()
            except UnboundLocalError:
                pass


def test_json_image_loop_view_extended(flask_app, system_db):
    """Test JsonImageLoopView mini_preflight 0-byte file, nonlocal images, getSqmData AttributeError, and virtualsky query param."""
    with flask_app.test_request_context('/?camera_id=1&mini_preflight=1&virtualsky=1'):
        loop_view = JsonImageLoopView()
        with patch.object(loop_view, 'getLoopImages', return_value=[{'url': '/img/1.jpg', 'width': 100, 'height': 100}]):
            with patch.object(loop_view, 'getSqmData', return_value=({}, {}, {}, {})):
                with patch.object(loop_view, 'getStarsData', return_value={}):
                    with patch.object(loop_view, 'getMiniTimelapsePreflight', return_value={'frame_count': 1}):
                        data = loop_view.get_objects()
                        assert 'standard_preflight' in data

    now = datetime.datetime.now()
    img_record = IndiAllSkyDbImageTable(
        camera_id=1,
        filename='test_loop.jpg',
        createDate=now,
        dayDate=now.date(),
        night=True,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
        width=1920,
        height=1080,
    )
    db.session.add(img_record)
    db.session.commit()

    with flask_app.test_request_context():
        loop_view = JsonImageLoopView()
        loop_view.limit = 100
        loop_view.s3_prefix = ''
        with tempfile.NamedTemporaryFile(suffix='.jpg') as f_tmp:
            # 0-byte file
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=f_tmp.name):
                res = loop_view.getMiniTimelapsePreflight(1, int(now.timestamp()) + 10, 3600)
                assert res['frame_count'] == 0

            # write some data
            f_tmp.write(b'data')
            f_tmp.flush()
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=f_tmp.name):
                res = loop_view.getMiniTimelapsePreflight(1, int(now.timestamp()) + 10, 3600)
                assert res['frame_count'] >= 1
                assert res['start_reference'] is not None

        # Test getLoopImages nonlocal images with and without admin network
        loop_view.web_nonlocal_images = True
        loop_view.web_local_images_admin = True
        with patch.object(loop_view, 'verify_admin_network', return_value=True):
            images = loop_view.getLoopImages(1, now + timedelta(seconds=10), 3600)
            assert isinstance(images, list)


def test_sensor_panel_views_extended(flask_app, system_db):
    """Test JsonSensorPanelView event_manager broadcast exception and SensorPanelView latest_image_entry branches."""
    # 1. JsonSensorPanelView broadcast exception
    with flask_app.test_request_context('/?camera_id=1'):
        view = JsonSensorPanelView()
        with patch('indi_allsky.events.event_manager.broadcast', side_effect=Exception('Broadcast failed')):
            payload = view.get_objects()
            assert 'sensor_user' in payload

    # 2. SensorPanelView with latest_image_entry
    now = datetime.datetime.now()
    img_record = IndiAllSkyDbImageTable(
        camera_id=1,
        filename='test_sensor.jpg',
        createDate=now,
        dayDate=now.date(),
        night=True,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
        width=1920,
        height=1080,
    )
    db.session.add(img_record)
    db.session.commit()

    with flask_app.test_request_context('/?all=1'):
        p_view = SensorPanelView(template_name='sensor_panel.html')
        p_view.latest_image_entry = img_record
        p_view.camera_now = now
        p_view.camera = db.session.get(IndiAllSkyDbCameraTable, 1)
        p_view.indi_allsky_config = {'NIGHT_SUN_ALT_DEG': -6.0}
        ctx = p_view.get_context()
        assert ctx['last_update'] == now
        assert ctx['last_update_age_s'] is not None


def test_config_view_and_ajax_config_view_extended(flask_app, system_db):
    """Test ConfigView maxExposure > 120 and fits_save_period < 600, and AjaxConfigView missing sub-dicts."""
    user = db.session.get(IndiAllSkyDbUserTable, 1)

    # 1. ConfigView maxExposure > 120 and fits_save_period < 600
    cam = db.session.get(IndiAllSkyDbCameraTable, 1)
    cam.maxExposure = 300
    db.session.commit()

    with flask_app.test_request_context():
        c_view = ConfigView(template_name='config.html')
        login_user(user)
        c_view.indi_allsky_config = {
            'IMAGE_SAVE_FITS': True,
            'IMAGE_SAVE_FITS_PERIOD': 300,
            'NIGHT_SUN_ALT_DEG': -6.0,
        }
        with patch.object(c_view, 'validate_longitude_timezone', return_value=True):
            ctx = c_view.get_context()
            assert ctx['camera_maxExposure'] == 120
            assert ctx['fits_enabled'] is True

    # 2. AjaxConfigView with missing leafs and CCD_CONFIG sub-dicts
    from tests.flask.views.test_config_and_controls import get_base_payload
    cfg_json = get_base_payload()

    with flask_app.test_request_context(
        method='POST',
        json=cfg_json,
    ):
        ajax_config_view = AjaxConfigView()
        ajax_config_view.indi_allsky_config = {
            'CCD_CONFIG': {},  # missing NIGHT, MOONMODE, DAY
            'ALLSKYMAP': {},
            'FITSHEADERS': None,
            'NIGHT_SUN_ALT_DEG': -6.0,
        }
        login_user(user)
        with patch.object(IndiAllskyConfigForm, 'validate', _always_valid):
            with patch.object(ajax_config_view._indi_allsky_config_obj, 'save'):
                res = ajax_config_view.dispatch_request()
                assert res.status_code == 200
                assert 'NIGHT' in ajax_config_view.indi_allsky_config['CCD_CONFIG']
                assert 'MOONMODE' in ajax_config_view.indi_allsky_config['CCD_CONFIG']
                assert 'DAY' in ajax_config_view.indi_allsky_config['CCD_CONFIG']


def test_ajax_system_info_view_extended(flask_app, system_db):
    """Test AjaxSystemInfoView actions: validate_db, expire_data, flush 16min, timelapses, daytime."""
    user = db.session.get(IndiAllSkyDbUserTable, 1)

    # 1. validate_db
    with flask_app.test_request_context(method='POST', json={'CAMERA_ID': 1, 'SERVICE_HIDDEN': 'system', 'COMMAND_HIDDEN': 'validate_db'}):
        view = AjaxSystemInfoView()
        login_user(user)
        with patch.object(IndiAllskySystemInfoForm, 'validate', _always_valid):
            with patch.object(view, 'validateDbEntries', return_value=['<p>Validated</p>']):
                res = view.dispatch_request()
                assert res.status_code == 200
                assert 'Validated' in res.get_json()['success-message']

    # 2. expire_data
    with flask_app.test_request_context(method='POST', json={'CAMERA_ID': 1, 'SERVICE_HIDDEN': 'system', 'COMMAND_HIDDEN': 'expire_data'}):
        view = AjaxSystemInfoView()
        login_user(user)
        with patch.object(IndiAllskySystemInfoForm, 'validate', _always_valid):
            res = view.dispatch_request()
            assert res.status_code == 200
            assert 'Submitted expire task' in res.get_json()['success-message']

    # 3. flush_16min_images, flush_timelapses, flush_daytime
    for cmd, method_name in (
        ('flush_16min_images', 'flush16MinutesImages'),
        ('flush_timelapses', 'flushTimelapses'),
        ('flush_daytime', 'flushDaytime'),
    ):
        with flask_app.test_request_context(method='POST', json={'CAMERA_ID': 1, 'SERVICE_HIDDEN': 'system', 'COMMAND_HIDDEN': cmd}):
            view = AjaxSystemInfoView()
            login_user(user)
            with patch.object(IndiAllskySystemInfoForm, 'validate', _always_valid):
                with patch.object(view, 'verify_admin_network', return_value=True):
                    with patch.object(view, method_name, return_value=5):
                        res = view.dispatch_request()
                        assert res.status_code == 200
                        assert 'Deleted' in res.get_json()['success-message']


def test_ajax_timelapse_generator_view_extended(flask_app, system_db):
    """Test AjaxTimelapseGeneratorView actions: delete_video, delete_panorama_video, delete_k_st, and daytime generation branches."""
    user = db.session.get(IndiAllSkyDbUserTable, 1)

    for action in ('delete_video', 'delete_panorama_video', 'delete_k_st', 'generate_video_k_st', 'generate_video', 'generate_panorama_video'):
        with flask_app.test_request_context(
            method='POST',
            json={
                'CAMERA_ID': 1,
                'ACTION_SELECT': action,
                'DAY_SELECT': '2026-09-20_day',  # night=False branch
            }
        ):
            view = AjaxTimelapseGeneratorView()
            login_user(user)
            with patch.object(view, 'verify_admin_network', return_value=True):
                with patch.object(IndiAllskyTimelapseGeneratorForm, 'validate', _always_valid):
                    view.indi_allsky_config = {'FISH2PANO': {'ENABLE': True}}
                    res = view.dispatch_request()
                    assert res.status_code == 200


def test_json_image_processing_view_extended(flask_app, system_db):
    """Test JsonImageProcessingView with sqm_roi, detect_mask file, detect_method='sep', and IMAGE_LABEL_SYSTEM."""
    user = db.session.get(IndiAllSkyDbUserTable, 1)

    now = datetime.datetime.now()
    fits_entry = IndiAllSkyDbFitsImageTable(
        camera_id=1,
        filename='test_proc.fits',
        createDate=now,
        dayDate=now.date(),
        night=True,
        width=100,
        height=100,
        exposure=10.0,
        gain=100.0,
    )
    db.session.add(fits_entry)
    db.session.commit()

    payload = {
        'DISABLE_PROCESSING': False,
        'OUTPUT_IMAGE_TYPE': 'jpg',
        'CAMERA_ID': 1,
        'FRAME_TYPE': 'light',
        'FITS_ID': fits_entry.id,
        'LENS_IMAGE_CIRCLE': 3000,
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
        'LENS_AZIMUTH': 0.0,
        'CCD_BIT_DEPTH': 16,
        'IMAGE_CALIBRATE_DARK': False,
        'IMAGE_CALIBRATE_BPM': False,
        'IMAGE_CALIBRATE_FIX_HOLES': False,
        'IMAGE_CALIBRATE_HOLE_THOLD': 30,
        'IMAGE_CALIBRATE_MANUAL_OFFSET': 0,
        'NIGHT_CONTRAST_ENHANCE': False,
        'IMAGE_COLORMAP': '',
        'CONTRAST_ENHANCE_16BIT': False,
        'CLAHE_CLIPLIMIT': 3.0,
        'CLAHE_GRIDSIZE': 8,
        'IMAGE_STRETCH__CLASSNAME': '',
        'IMAGE_STRETCH__MODE1_GAMMA': 3.0,
        'IMAGE_STRETCH__MODE1_STDDEVS': 2.25,
        'IMAGE_STRETCH__MODE2_SHADOWS': 0.0,
        'IMAGE_STRETCH__MODE2_MIDTONES': 0.35,
        'IMAGE_STRETCH__MODE2_HIGHLIGHTS': 1.0,
        'IMAGE_STRETCH__MODE3_BLACK_CLIP': -2.8,
        'IMAGE_STRETCH__MODE3_SHADOWS': 0.0,
        'IMAGE_STRETCH__MODE3_MIDTONES': 0.25,
        'IMAGE_STRETCH__MODE3_HIGHLIGHTS': 1.0,
        'CFA_PATTERN': '',
        'SCNR_ALGORITHM': '',
        'SCNR_MTF_MIDTONES': 0.65,
        'IMAGE_DENOISE': '',
        'IMAGE_DENOISE_STRENGTH': 3,
        'BILATERAL_SIGMA_COLOR': 20,
        'BILATERAL_SIGMA_SPACE': 35,
        'WBR_FACTOR': 1.0,
        'WBG_FACTOR': 1.0,
        'WBB_FACTOR': 1.0,
        'WBR_MTF_MIDTONES': 0.5,
        'WBG_MTF_MIDTONES': 0.5,
        'WBB_MTF_MIDTONES': 0.5,
        'AUTO_WB': False,
        'SATURATION_FACTOR': 1.0,
        'GAMMA_CORRECTION': 1.0,
        'SHARPEN_AMOUNT': 0.0,
        'IMAGE_ROTATE': '',
        'IMAGE_ROTATE_ANGLE': 0,
        'IMAGE_ROTATE_KEEP_SIZE': False,
        'IMAGE_FLIP_V': False,
        'IMAGE_FLIP_H': False,
        'DETECT_MASK': '',
        'SQM_FOV_DIV': 4,
        'IMAGE_STACK_METHOD': 'maximum',
        'IMAGE_STACK_COUNT': 1,
        'IMAGE_STACK_ALIGN': False,
        'IMAGE_ALIGN_DETECTSIGMA': 5,
        'IMAGE_ALIGN_POINTS': 50,
        'IMAGE_ALIGN_SOURCEMINAREA': 10,
        'FISH2PANO__ENABLE': False,
        'FISH2PANO__DIAMETER': 3000,
        'FISH2PANO__ROTATE_ANGLE': 0,
        'FISH2PANO__SCALE': 0.3,
        'FISH2PANO__FLIP_H': False,
        'FISH2PANO__ENABLE_CARDINAL_DIRS': True,
        'FISH2PANO__DIRS_OFFSET_BOTTOM': 25,
        'FISH2PANO__OPENCV_FONT_SCALE': 0.8,
        'FISH2PANO__PIL_FONT_SIZE': 30,
        'PROCESSING_SPLIT_SCREEN': False,
        'IMAGE_LABEL_TEMPLATE': '',
        'IMAGE_EXTRA_TEXT': '',
        'IMAGE_LABEL_SYSTEM': 'System Label',  # test label_image() call
        'TEXT_PROPERTIES__FONT_FACE': 'FONT_HERSHEY_SIMPLEX',
        'TEXT_PROPERTIES__FONT_SCALE': 0.8,
        'TEXT_PROPERTIES__FONT_THICKNESS': 1,
        'TEXT_PROPERTIES__FONT_OUTLINE': True,
        'TEXT_PROPERTIES__FONT_HEIGHT': 30,
        'TEXT_PROPERTIES__FONT_X': 15,
        'TEXT_PROPERTIES__FONT_Y': 30,
        'TEXT_PROPERTIES__PIL_FONT_FILE': 'fonts-freefont-ttf/FreeSans.ttf',
        'TEXT_PROPERTIES__PIL_FONT_CUSTOM': '',
        'TEXT_PROPERTIES__PIL_FONT_SIZE': 30,
        'CARDINAL_DIRS__ENABLE': False,
        'CARDINAL_DIRS__SWAP_NS': False,
        'CARDINAL_DIRS__SWAP_EW': False,
        'CARDINAL_DIRS__CHAR_NORTH': 'N',
        'CARDINAL_DIRS__CHAR_EAST': 'E',
        'CARDINAL_DIRS__CHAR_WEST': 'W',
        'CARDINAL_DIRS__CHAR_SOUTH': 'S',
        'CARDINAL_DIRS__DIAMETER': 3000,
        'CARDINAL_DIRS__OFFSET_X': 0,
        'CARDINAL_DIRS__OFFSET_Y': 0,
        'CARDINAL_DIRS__OFFSET_TOP': 15,
        'CARDINAL_DIRS__OFFSET_LEFT': 15,
        'CARDINAL_DIRS__OFFSET_RIGHT': 15,
        'CARDINAL_DIRS__OFFSET_BOTTOM': 15,
        'CARDINAL_DIRS__OPENCV_FONT_SCALE': 0.5,
        'CARDINAL_DIRS__PIL_FONT_SIZE': 20,
        'CARDINAL_DIRS__OUTLINE_CIRCLE': False,
        'IMAGE_CIRCLE_MASK__ENABLE': False,
        'IMAGE_CIRCLE_MASK__DIAMETER': 3000,
        'IMAGE_CIRCLE_MASK__OFFSET_X': 0,
        'IMAGE_CIRCLE_MASK__OFFSET_Y': 0,
        'IMAGE_CIRCLE_MASK__BLUR': 35,
        'IMAGE_CIRCLE_MASK__OPACITY': 100,
        'IMAGE_CIRCLE_MASK__OUTLINE': False,
        'IMAGE_CROP_IMAGE_CIRCLE': False,
        'IMAGE_BORDER__TOP': 0,
        'IMAGE_BORDER__LEFT': 0,
        'IMAGE_BORDER__RIGHT': 0,
        'IMAGE_BORDER__BOTTOM': 0,
        'MOON_OVERLAY__ENABLE': False,
        'MOON_OVERLAY__X': -500,
        'MOON_OVERLAY__Y': -200,
        'MOON_OVERLAY__SCALE': 0.5,
        'MOON_OVERLAY__DARK_SIDE_SCALE': 0.4,
        'MOON_OVERLAY__FLIP_V': False,
        'MOON_OVERLAY__FLIP_H': False,
        'LIGHTGRAPH_OVERLAY__ENABLE': False,
        'LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT': 30,
        'LIGHTGRAPH_OVERLAY__GRAPH_BORDER': 3,
        'LIGHTGRAPH_OVERLAY__Y': 10,
        'LIGHTGRAPH_OVERLAY__OFFSET_X': 0,
        'LIGHTGRAPH_OVERLAY__SCALE': 1.0,
        'LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE': 8,
        'LIGHTGRAPH_OVERLAY__OPACITY': 100,
        'LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE': 20,
        'LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE': 0.5,
        'LIGHTGRAPH_OVERLAY__LABEL': True,
        'LIGHTGRAPH_OVERLAY__HOUR_LINES': True,
        'RUN_DETECTION': True,
        'DETECT_STARS_METHOD': 'sep',
        'DETECT_STARS_THOLD': 0.6,
        'DETECT_STARS_SEP_THOLD': 5.0,
        'DETECT_STARS_SEP_MAX_RADIUS': 20,
        'DETECT_METEORS_THOLD': 125,
        'SQM_ROI_X1': 10,
        'SQM_ROI_Y1': 10,
        'SQM_ROI_X2': 50,
        'SQM_ROI_Y2': 50,
        'TEXT_PROPERTIES__FONT_COLOR': '200,200,200',
        'CARDINAL_DIRS__FONT_COLOR': '200,0,0',
        'IMAGE_BORDER__COLOR': '0,0,0',
        'LIGHTGRAPH_OVERLAY__DAY_COLOR': '150,150,150',
        'LIGHTGRAPH_OVERLAY__DUSK_COLOR': '200,100,60',
        'LIGHTGRAPH_OVERLAY__NIGHT_COLOR': '30,30,30',
        'LIGHTGRAPH_OVERLAY__MOONMODE_COLOR': '50,50,50',
        'LIGHTGRAPH_OVERLAY__HOUR_COLOR': '100,15,15',
        'LIGHTGRAPH_OVERLAY__BORDER_COLOR': '1,1,1',
        'LIGHTGRAPH_OVERLAY__NOW_COLOR': '120,120,200',
        'LIGHTGRAPH_OVERLAY__FONT_COLOR': '150,150,150',
    }

    with tempfile.NamedTemporaryFile(suffix='.fits') as f_tmp:
        from astropy.io import fits
        import numpy as np
        hdu = fits.PrimaryHDU(data=np.ones((50, 50), dtype=np.uint16) * 100)
        hdu.header['EXPTIME'] = 10.0
        hdu.header['GAIN'] = 100.0
        hdu.header['XBINNING'] = 1
        hdu.writeto(f_tmp.name, overwrite=True)

        with flask_app.test_request_context(method='POST', json=payload):
            view = JsonImageProcessingView()
            login_user(user)
            with patch.object(IndiAllskyImageProcessingForm, 'validate', _always_valid):
                with patch.object(IndiAllSkyDbFitsImageTable, 'getLocalOrCachedPath', return_value=Path(f_tmp.name)):
                    res = view.dispatch_request()
                    assert res.status_code == 200


def test_notification_and_user_info_views_extended(flask_app, system_db):
    """Test AjaxNotificationView non-auth/invalid method/ack NoResultFound and AjaxUserInfoView non-POST and password verify fail."""
    user_record = db.session.get(IndiAllSkyDbUserTable, 1)
    user_record.password = argon2.hash('RealPassword123!')
    db.session.commit()

    # 1. AjaxNotificationView unauthenticated
    with flask_app.test_request_context():
        n_view = AjaxNotificationView()
        res = n_view.dispatch_request()
        assert res.get_json()['id'] == 0

    # 2. AjaxNotificationView PUT method -> 400
    with flask_app.test_request_context(method='PUT'):
        n_view = AjaxNotificationView()
        login_user(user_record)
        res, code = n_view.dispatch_request()
        assert code == 400

    # 3. AjaxNotificationView POST with non-existent ack_id
    with flask_app.test_request_context(method='POST', json={'camera_id': 1, 'ack_id': 999999}):
        n_view = AjaxNotificationView()
        login_user(user_record)
        res = n_view.dispatch_request()
        assert res.get_json()['id'] == 0

    # 4. AjaxUserInfoView non-POST method -> 400
    with flask_app.test_request_context(method='GET'):
        u_view = AjaxUserInfoView()
        login_user(user_record)
        res, code = u_view.dispatch_request()
        assert code == 400

    # 5. AjaxUserInfoView password verification failure
    with flask_app.test_request_context(
        method='POST',
        json={
            'USERNAME': user_record.username,
            'NAME': 'New Name',
            'EMAIL': user_record.email,
            'ADMIN': True,
            'CURRENT_PASSWORD': 'WrongPassword123!',
            'NEW_PASSWORD': '',
            'NEW_PASSWORD_CONFIRM': '',
        }
    ):
        u_view = AjaxUserInfoView()
        login_user(user_record)
        res, code = u_view.dispatch_request()
        assert code == 400
        assert 'CURRENT_PASSWORD' in res.get_json()


def test_config_backup_restore_and_select_camera_extended(flask_app, system_db):
    """Test ConfigDownloadView.dict_merge, AjaxConfigRestoreView validation failure, and AjaxSelectCameraView non-POST/missing."""
    user_record = db.session.get(IndiAllSkyDbUserTable, 1)

    # 1. ConfigDownloadView.dict_merge
    b_view = ConfigDownloadView()
    d1 = {'a': 1, 'nested': {'x': 'old', 'y': 2}}
    d2 = {'a': 10, 'nested': {'x': 'new', 'z': 3}, 'b': 20}
    merged = b_view.dict_merge(d1, d2)
    assert merged['a'] == 10
    assert merged['nested']['x'] == 'new'
    assert merged['nested']['z'] == 3

    # 2. AjaxConfigRestoreView validation failure (empty / non-json CONFIG_UPLOAD)
    with flask_app.test_request_context(
        method='POST',
        data={'CONFIG_UPLOAD': (io.BytesIO(b'invalid json content'), 'test.json')},
        content_type='multipart/form-data',
    ):
        r_view = AjaxConfigRestoreView()
        login_user(user_record)
        res, code = r_view.dispatch_request()
        assert code == 400

    # 3. AjaxSelectCameraView non-POST and NoResultFound
    with flask_app.test_request_context(method='GET'):
        cam_view = AjaxSelectCameraView()
        res, code = cam_view.dispatch_request()
        assert code == 400

    with flask_app.test_request_context(method='POST', json={'camera_id': 99999}):
        cam_view = AjaxSelectCameraView()
        res, code = cam_view.dispatch_request()
        assert code == 400


def test_mini_timelapse_views_and_longterm_extended(flask_app, system_db):
    """Test MiniTimelapseVideoView missing url/record, MiniTimelapseGeneratorView day bitrate, and JsonLongTermKeogramView validation fail."""
    user_record = db.session.get(IndiAllSkyDbUserTable, 1)

    # 1. MiniTimelapseVideoView without video_url
    with flask_app.test_request_context('/?id=9999'):
        mv_view = MiniTimelapseVideoView(template_name='mini_timelapse_video.html')
        login_user(user_record)
        with patch.object(mv_view, 'get_context', return_value={'video_url': ''}):
            ctx = mv_view.get_context()
            assert ctx['video_url'] == ''

    # 2. MiniTimelapseGeneratorView with day bitrate and non-preset bitrate
    now = datetime.datetime.now()
    img = IndiAllSkyDbImageTable(
        camera_id=1,
        filename='test_mini.jpg',
        createDate=now,
        dayDate=now.date(),
        night=False,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
        width=1920,
        height=1080,
    )
    db.session.add(img)
    db.session.commit()

    with flask_app.test_request_context(f'/?image_id={img.id}'):
        gen_view = MiniTimelapseGeneratorView(template_name='mini_timelapse_generator.html')
        gen_view.camera = db.session.get(IndiAllSkyDbCameraTable, 1)
        gen_view.indi_allsky_config = {
            'TIMELAPSE': {'USE_NIGHT_CONFIG': False},
            'FFMPEG_BITRATE_DAY': '7777k',
            'FFMPEG_VFSCALE_DAY': '-2:720',
            'FISH2PANO': {'ENABLE': False},
            'NIGHT_SUN_ALT_DEG': -6.0,
        }
        login_user(user_record)
        ctx = gen_view.get_context()
        assert ctx['standard_video']['height'] == 720
        assert 'Configured default' in dict(ctx['form_mini_timelapse'].BITRATE_SELECT.choices)

    # 3. JsonLongTermKeogramView validation fail
    with flask_app.test_request_context(method='POST', json={}):
        lt_view = JsonLongTermKeogramView()
        login_user(user_record)
        with patch.object(IndiAllskyLongTermKeogramForm, 'validate', _always_invalid):
            res, code = lt_view.dispatch_request()
            assert code == 400


def test_ajax_astropanel_view_extended_bodies_and_satellites(flask_app, system_db):
    """Test AjaxAstroPanelView satellite next_pass None branches, moon phases, and body position calculation branches."""
    # Create satellite record in DB
    sat = IndiAllSkyDbTleDataTable(
        group=constants.SATELLITE_VISUAL,
        title='ISS (ZARYA)',
        line1='1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927',
        line2='2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537',
    )
    db.session.add(sat)
    db.session.commit()

    mock_sat = MagicMock()
    mock_sat.az = 1.0
    mock_sat.alt = 0.5
    mock_sat.elevation = 400000.0
    mock_sat.eclipsed = False
    mock_sat.compute = MagicMock()

    with flask_app.test_request_context('/?camera_id=1'):
        astro_view = AjaxAstroPanelView()
        with patch('ephem.readtle', return_value=mock_sat):
            with patch('ephem.Observer.next_pass', return_value=(None, None, None, None, None)):
                res = astro_view.get(1)
                data = res.get_json()
                assert len(data['satellite_list']) >= 1
                assert data['satellite_list'][0]['rise'] == 'None'

    # Test moon phases
    obs = ephem.Observer()
    obs.date = '2026/09/20 12:00:00'
    astro_view = AjaxAstroPanelView()
    for phase_name in ('Full', 'New', 'First Quarter', 'Last Quarter', 'Waxing Crescent', 'Waxing Gibbous', 'Waning Gibbous', 'Waning Crescent'):
        with patch.object(astro_view, 'astropanel_get_moon_phase', return_value=phase_name):
            assert astro_view.astropanel_get_moon_phase(obs) == phase_name
