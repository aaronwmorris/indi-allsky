import os
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbDarkFrameTable,
    IndiAllSkyDbBadPixelMapTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbRawImageTable,
)


@pytest.fixture
def loops_db(flask_app):
    """Seed DB for loops, charts, and sensor views."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbImageTable).delete()
        db.session.query(IndiAllSkyDbPanoramaImageTable).delete()
        db.session.query(IndiAllSkyDbRawImageTable).delete()
        db.session.query(IndiAllSkyDbDarkFrameTable).delete()
        db.session.query(IndiAllSkyDbBadPixelMapTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="22222222-2222-2222-2222-222222222222",
            latitude=-34.0,
            longitude=138.0,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
            hidden=False,
            utc_offset=36000.0,
            lensFocalLength=4.0,
            lensFocalRatio=2.0,
            lensImageCircle=180.0,
            cfa=None,
            owner="Admin",
            connectDate=datetime.now(),
            width=1920,
            height=1080,
            pixelSize=2.4,
            data={
                'custom_chart_1_key': 'sensor_user_10',
                'sensor_user_10': 'Custom Label 1',
            },
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FOLDER': '/tmp',
            },
            level="1.0",
            note='test',
        )
        db.session.add(config_entry)

        admin = IndiAllSkyDbUserTable(
            username="admin",
            password="hashed_password",
            email="admin@example.org",
            name="Admin",
            active=True,
            admin=True,
        )
        db.session.add(admin)

        img = IndiAllSkyDbImageTable(
            id=1,
            camera_id=1,
            filename="image1.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=1000.0,
            sqm=21.5,
            stars=500,
            temp=15.0,
            detections=2,
            exclude=False,
            night=True,
            data={
                'sensor_user_7': 20.5,
                'sensor_user_8': 21.0,
                'sensor_user_9': 1000.0,
            },
        )
        db.session.add(img)

        dark = IndiAllSkyDbDarkFrameTable(
            id=1,
            camera_id=1,
            filename="dark1.fits",
            createDate=datetime.now(),
            active=True,
            bitdepth=16,
            gain=100.0,
            exposure=1.0,
            binmode=1,
            width=1920,
            height=1080,
            temp=15.0,
            adu=100.0,
            data={'hot_pixels': 10, 'method': 'median'},
        )
        db.session.add(dark)

        bpm = IndiAllSkyDbBadPixelMapTable(
            id=1,
            camera_id=1,
            filename="bpm1.fits",
            createDate=datetime.now(),
            active=True,
            bitdepth=16,
            gain=100.0,
            exposure=1.0,
            binmode=1,
            width=1920,
            height=1080,
            temp=15.0,
            adu=100.0,
            data={'hot_pixels': 5},
        )
        db.session.add(bpm)

        pano = IndiAllSkyDbPanoramaImageTable(
            id=1,
            camera_id=1,
            filename="pano1.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            width=1920,
            height=1080,
            exclude=False,
            night=True,
        )
        db.session.add(pano)

        raw_img = IndiAllSkyDbRawImageTable(
            id=1,
            camera_id=1,
            filename="raw1.raw",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            night=True,
        )
        db.session.add(raw_img)

        db.session.commit()
        yield
        db.session.remove()


def test_misc_template_views(flask_app, loops_db):
    client = flask_app.test_client()

    mask_file = Path('/tmp/mask_base.png')
    mask_file.touch()

    try:
        with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
            # MaskView context (with mask file)
            res_mask = client.get('/indi-allsky/mask?camera_id=1')
            assert res_mask.status_code == 200

            # CamerasView context
            res_cams = client.get('/indi-allsky/cameras?camera_id=1')
            assert res_cams.status_code == 200

            # DarkFramesView context
            res_darks = client.get('/indi-allsky/darks?camera_id=1')
            assert res_darks.status_code == 200

            # ImageLagView context
            res_lag = client.get('/indi-allsky/lag?camera_id=1&timestamp=1234567890')
            assert res_lag.status_code == 200

            # RollingAduView context
            res_adu = client.get('/indi-allsky/adu?camera_id=1')
            assert res_adu.status_code == 200

            # SqmView context
            res_sqm = client.get('/indi-allsky/sqm?camera_id=1')
            assert res_sqm.status_code == 200
    finally:
        if mask_file.exists():
            mask_file.unlink()


def test_image_loop_views_unpatched(flask_app, loops_db):
    client = flask_app.test_client()

    # Image Loop Canvas & Img & Json
    res_lc = client.get('/indi-allsky/loop_canvas?camera_id=1')
    assert res_lc.status_code == 200

    res_li = client.get('/indi-allsky/loop_img?camera_id=1')
    assert res_li.status_code == 200

    # JSON Image Loop with mini_preflight and limit_s > 14400
    res_js = client.get('/indi-allsky/js/loop?camera_id=1&limit_s=15000&mini_preflight=1')
    assert res_js.status_code == 200
    data = res_js.get_json()
    assert 'image_list' in data
    assert 'standard_preflight' in data


def test_panorama_loop_views_unpatched(flask_app, loops_db):
    client = flask_app.test_client()

    res_pc = client.get('/indi-allsky/looppanorama_canvas?camera_id=1')
    assert res_pc.status_code == 200

    res_pi = client.get('/indi-allsky/looppanorama_img?camera_id=1')
    assert res_pi.status_code == 200

    # JSON Panorama Loop with source dimensions preflight
    res_pj = client.get('/indi-allsky/js/looppanorama?camera_id=1&source_width=1920&source_height=1080')
    assert res_pj.status_code == 200
    data = res_pj.get_json()
    assert 'panorama_preflight' in data


def test_raw_image_loop_views_unpatched(flask_app, loops_db):
    client = flask_app.test_client()

    res_rc = client.get('/indi-allsky/loopraw_canvas?camera_id=1')
    assert res_rc.status_code == 200

    res_ri = client.get('/indi-allsky/loopraw_img?camera_id=1')
    assert res_ri.status_code == 200

    res_rj = client.get('/indi-allsky/js/loopraw?camera_id=1')
    assert res_rj.status_code == 200


def test_charts_and_sensor_panel_views_unpatched(flask_app, loops_db):
    client = flask_app.test_client()

    # ChartView
    res_chart = client.get('/indi-allsky/charts?camera_id=1')
    assert res_chart.status_code == 200

    # JsonChartView with limit_s > 86400
    res_jschart = client.get('/indi-allsky/js/charts?camera_id=1&limit_s=90000')
    assert res_jschart.status_code == 200
    chart_data = res_jschart.get_json()
    assert 'chart_data' in chart_data

    # SensorPanelView & JsonSensorPanelView
    res_sensor = client.get('/indi-allsky/sensor_panel?camera_id=1&all=1')
    assert res_sensor.status_code == 200

    res_sensor0 = client.get('/indi-allsky/sensor_panel?camera_id=1&all=0')
    assert res_sensor0.status_code == 200

    res_jssensor = client.get('/indi-allsky/js/sensor_panel?camera_id=1')
    assert res_jssensor.status_code == 200


def test_sensor_panel_no_latest_image(flask_app, loops_db):
    client = flask_app.test_client()
    with flask_app.app_context():
        IndiAllSkyDbImageTable.query.delete()
        db.session.commit()

    res_sensor = client.get('/indi-allsky/sensor_panel?camera_id=1')
    assert res_sensor.status_code == 200

    res_jssensor = client.get('/indi-allsky/js/sensor_panel?camera_id=1')
    assert res_jssensor.status_code == 200
    data = res_jssensor.get_json()
    assert data['last_update'] is None


def test_json_chart_histogram_jpg(flask_app, loops_db):
    import numpy as np
    import cv2
    from datetime import datetime, timedelta

    client = flask_app.test_client()
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        offset = cam.utc_offset - datetime.now().astimezone().utcoffset().total_seconds()
        camera_now = datetime.now() + timedelta(seconds=offset)

        img_rec = db.session.get(IndiAllSkyDbImageTable, 1)
        img_rec.createDate = camera_now - timedelta(seconds=60)
        db.session.commit()

    img_path = Path('/tmp/image1.jpg')
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.imwrite(str(img_path), img)

    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
            data = res.get_json()['chart_data']
            assert len(data['histogram']['red']) == 256
    finally:
        if img_path.exists():
            img_path.unlink()

    # Corrupt JPG
    img_path.write_bytes(b'not a real jpeg')
    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
    finally:
        if img_path.exists():
            img_path.unlink()


def test_json_chart_histogram_png(flask_app, loops_db):
    import numpy as np
    import cv2
    from datetime import datetime, timedelta

    client = flask_app.test_client()
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        offset = cam.utc_offset - datetime.now().astimezone().utcoffset().total_seconds()
        camera_now = datetime.now() + timedelta(seconds=offset)

        img_rec = db.session.get(IndiAllSkyDbImageTable, 1)
        img_rec.filename = 'image1.png'
        img_rec.createDate = camera_now - timedelta(seconds=60)
        db.session.commit()

    # Color PNG
    img_path = Path('/tmp/image1.png')
    img = np.ones((100, 100, 3), dtype=np.uint8) * 128
    cv2.imwrite(str(img_path), img)

    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
            data = res.get_json()['chart_data']
            assert len(data['histogram']['red']) == 256
    finally:
        if img_path.exists():
            img_path.unlink()

    # Mono PNG
    img_mono = np.ones((100, 100), dtype=np.uint8) * 100
    cv2.imwrite(str(img_path), img_mono)

    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
            data = res.get_json()['chart_data']
            assert len(data['histogram']['gray']) == 256
    finally:
        if img_path.exists():
            img_path.unlink()

    # Corrupt PNG
    img_path.write_bytes(b'invalid png')
    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
    finally:
        if img_path.exists():
            img_path.unlink()




def test_json_chart_histogram_pil_and_sqm(flask_app, loops_db):
    import numpy as np
    from PIL import Image
    from datetime import datetime, timedelta

    client = flask_app.test_client()
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        offset = cam.utc_offset - datetime.now().astimezone().utcoffset().total_seconds()
        camera_now = datetime.now() + timedelta(seconds=offset)

        img_rec = db.session.get(IndiAllSkyDbImageTable, 1)
        img_rec.filename = 'image1.tif'
        img_rec.createDate = camera_now - timedelta(seconds=60)

        cfg = db.session.query(IndiAllSkyDbConfigTable).first()
        cfg.data['SQM_ROI'] = [10, 10, 50, 50]
        db.session.commit()

    img_path = Path('/tmp/image1.tif')
    img = Image.new('RGB', (100, 100), color=(200, 100, 50))
    img.save(str(img_path))

    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
    finally:
        if img_path.exists():
            img_path.unlink()

    # Corrupt TIFF
    img_path.write_bytes(b'invalid tiff')
    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            res = client.get('/indi-allsky/js/charts?camera_id=1')
            assert res.status_code == 200
    finally:
        if img_path.exists():
            img_path.unlink()



def test_json_chart_histogram_mask_loader(flask_app, loops_db):
    import numpy as np
    import cv2
    from datetime import datetime, timedelta

    client = flask_app.test_client()
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        offset = cam.utc_offset - datetime.now().astimezone().utcoffset().total_seconds()
        camera_now = datetime.now() + timedelta(seconds=offset)

        img_rec = db.session.get(IndiAllSkyDbImageTable, 1)
        img_rec.createDate = camera_now - timedelta(seconds=60)
        db.session.commit()

    img_path = Path('/tmp/image1.jpg')
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.imwrite(str(img_path), img)

    mock_mask = np.ones((100, 100), dtype=np.uint8)

    try:
        with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=img_path):
            with patch('indi_allsky.flask.views.JsonChartView._load_detection_mask', return_value=mock_mask):
                res = client.get('/indi-allsky/js/charts?camera_id=1')
                assert res.status_code == 200
    finally:
        if img_path.exists():
            img_path.unlink()



def test_config_views_context_branches(flask_app, loops_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        cam.utc_offset = datetime.now().astimezone().utcoffset().total_seconds()
        img = db.session.get(IndiAllSkyDbImageTable, 1)
        img.createDate = datetime.now()
        db.session.commit()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # 1. Automatic dew heater thresholds (high, med, low, default) & Fan thresholds (high, med, low, default)
        test_cases = [
            # dh_t, dh_dp, sqm_raw_mag
            (5.0, 20.0, -5.0),   # dh delta = -15 (high <= -5), fan delta = -15 (default)
            (10.0, 20.0, 0.0),   # dh delta = -10 (med <= -10), fan delta = -10 (low >= -10)
            (12.0, 20.0, 0.0),   # dh delta = -8 (low <= -15 is false, <=-10 false, <=-5 true -> wait, check thresholds)
            (18.0, 20.0, 0.0),   # dh delta = -2 (> -5 -> default), fan delta = -2 (med >= -5)
            (25.0, 20.0, 0.0),   # fan delta = 5 (high >= 0)
        ]
        for dh_t, dh_dp, sqm in test_cases:
            with flask_app.app_context():
                img = db.session.get(IndiAllSkyDbImageTable, 1)
                img.createDate = datetime.now()
                img.data = {
                    'camera_sqm_raw_mag': sqm,
                    'sensor_user_10': dh_t,
                    'sensor_user_2': dh_dp,
                }
                db.session.commit()
            res = client.get('/indi-allsky/config?camera_id=1')
            assert res.status_code == 200

        # 2. Manual dew heater target & manual fan target
        for dh_t, manual_target in [(5.0, 15.0), (10.0, 15.0), (13.0, 15.0), (20.0, 15.0)]:
            with flask_app.app_context():
                cfg = db.session.query(IndiAllSkyDbConfigTable).first()
                data = dict(cfg.data)
                data['DEW_HEATER'] = {'MANUAL_TARGET': manual_target}
                data['FAN'] = {'MANUAL_TARGET': manual_target}
                cfg.data = data
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(cfg, 'data')
                img = db.session.get(IndiAllSkyDbImageTable, 1)
                img.createDate = datetime.now()
                img.data = {
                    'camera_sqm_raw_mag': 0.0,
                    'sensor_user_10': dh_t,
                    'sensor_user_2': 10.0,
                }
                db.session.commit()
            res_manual = client.get('/indi-allsky/config?camera_id=1')
            assert res_manual.status_code == 200

        # 3. Missing temperature / dewpoint data
        with flask_app.app_context():
            img = db.session.get(IndiAllSkyDbImageTable, 1)
            img.createDate = datetime.now()
            img.data = {}  # no sensor data
            db.session.commit()
        res_no_data = client.get('/indi-allsky/config?camera_id=1')
        assert res_no_data.status_code == 200

        # 4. Longitude validation failure warning
        with patch('indi_allsky.flask.views.ConfigView.validate_longitude_timezone', return_value=False):
            res_warn = client.get('/indi-allsky/config?camera_id=1')
            assert res_warn.status_code == 200
            assert b'Warning: Longitude validation failed' in res_warn.data


def test_sensor_panel_view_branches(flask_app, loops_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        img = db.session.get(IndiAllSkyDbImageTable, 1)
        img.data = {
            'camera_sqm_raw_mag': -5.0,
            'sensor_user_10': 20.0,
            'sensor_user_2': 28.0,
        }
        db.session.commit()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # GET /indi-allsky/sensor_panel
        res = client.get('/indi-allsky/sensor_panel?camera_id=1')
        assert res.status_code == 200

        # GET /indi-allsky/js/sensor_panel
        res_js = client.get('/indi-allsky/js/sensor_panel?camera_id=1')
        assert res_js.status_code == 200


def test_json_chart_view_deep_branches(flask_app, loops_db, tmp_path):
    import cv2
    import numpy as np

    client = flask_app.test_client()

    png_path = tmp_path / "latest.png"
    # Create mono 2D image
    mono_img = np.zeros((100, 100), dtype=np.uint8)
    cv2.imwrite(str(png_path), mono_img)

    with flask_app.app_context():
        img = db.session.get(IndiAllSkyDbImageTable, 1)
        img.detections = 3
        img.temp = 20.0
        img.data = {
            'sensor_user_10': 1.1,
            'sensor_user_11': 2.2,
            'sensor_user_12': 3.3,
            'sensor_user_13': 4.4,
            'sensor_user_14': 5.5,
            'sensor_user_15': 6.6,
            'sensor_user_16': 7.7,
            'sensor_user_17': 8.8,
            'sensor_user_18': 9.9,
        }
        db.session.commit()

    with patch.dict(flask_app.config, {'LOGIN_DISABLED': True}):
        # Fahrenheit temp display
        with patch.object(flask_app.config, 'get', side_effect=lambda k, d=None: 'f' if k == 'TEMP_DISPLAY' else d):
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=png_path):
                res_f = client.get('/indi-allsky/js/charts?camera_id=1')
                assert res_f.status_code == 200

        # Kelvin temp display
        with patch.object(flask_app.config, 'get', side_effect=lambda k, d=None: 'k' if k == 'TEMP_DISPLAY' else d):
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=png_path):
                res_k = client.get('/indi-allsky/js/charts?camera_id=1')
                assert res_k.status_code == 200

        # Color image (3D array) with custom SQM_ROI
        color_path = tmp_path / "latest_color.png"
        color_img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(color_path), color_img)

        with patch.object(flask_app.config, 'get', side_effect=lambda k, d=None: [10, 10, 90, 90] if k == 'SQM_ROI' else d):
            with patch.object(IndiAllSkyDbImageTable, 'getFilesystemPath', return_value=color_path):
                res_color = client.get('/indi-allsky/js/charts?camera_id=1')
                assert res_color.status_code == 200


def test_sensor_panel_with_dew_heater_and_fan_branches(flask_app, loops_db):
    client = flask_app.test_client()

    with flask_app.app_context():
        img = db.session.get(IndiAllSkyDbImageTable, 1)

    with flask_app.app_context():
        img.data = {
            'camera_sqm_raw_mag': -3.5,
            'sensor_user_10': 5.0,
            'sensor_user_2': 12.0,
        }
        db.session.commit()

    res1 = client.get('/indi-allsky/sensor_panel?camera_id=1')
    assert res1.status_code == 200

    with flask_app.app_context():
        img.data = {
            'camera_sqm_raw_mag': 0.0,
            'sensor_user_10': 28.0,
            'sensor_user_2': 39.0,
        }
        db.session.commit()

    res2 = client.get('/indi-allsky/sensor_panel?camera_id=1')
    assert res2.status_code == 200

    with flask_app.app_context():
        img.data = {
            'sensor_user_10': 23.0,
            'sensor_user_2': 37.0,
        }
        db.session.commit()

    res3 = client.get('/indi-allsky/sensor_panel?camera_id=1')
    assert res3.status_code == 200

    with flask_app.app_context():
        img.data = {
            'sensor_user_10': 15.0,
            'sensor_user_2': 5.0,
        }
        db.session.commit()

    res4 = client.get('/indi-allsky/sensor_panel?camera_id=1')
    assert res4.status_code == 200

    # Manual dew heater target
    config_dew_heater_manual = {
        'DEW_HEATER': {
            'MANUAL_TARGET': 15.0,
            'THOLD_DIFF_LOW': -15,
            'THOLD_DIFF_MED': -10,
            'THOLD_DIFF_HIGH': -5,
            'LEVEL_DEF': 0,
            'LEVEL_LOW': 33,
            'LEVEL_MED': 66,
            'LEVEL_HIGH': 100,
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        },
        'FAN': {
            'TARGET': 30.0,
            'THOLD_DIFF_LOW': -10,
            'THOLD_DIFF_MED': -5,
            'THOLD_DIFF_HIGH': 0,
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        }
    }
    with patch.dict(flask_app.config, {'INDI_ALLSKY_CONFIG': config_dew_heater_manual}):
        with flask_app.app_context():
            img.data = {
                'sensor_user_10': 8.0,
            }
            db.session.commit()

        res5 = client.get('/indi-allsky/sensor_panel?camera_id=1')
        assert res5.status_code == 200

        with flask_app.app_context():
            img.data = {}
            db.session.commit()

        res6 = client.get('/indi-allsky/sensor_panel?camera_id=1')
        assert res6.status_code == 200

