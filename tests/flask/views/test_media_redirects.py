import pytest
from datetime import datetime
from unittest.mock import patch
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbKeogramTable,
    IndiAllSkyDbStarTrailsTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaVideoTable,
)


@pytest.fixture
def redirect_db(flask_app):
    """Seed DB for redirect views testing."""
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbImageTable).delete()
        db.session.query(IndiAllSkyDbKeogramTable).delete()
        db.session.query(IndiAllSkyDbStarTrailsTable).delete()
        db.session.query(IndiAllSkyDbPanoramaImageTable).delete()
        db.session.query(IndiAllSkyDbRawImageTable).delete()
        db.session.query(IndiAllSkyDbThumbnailTable).delete()
        db.session.query(IndiAllSkyDbVideoTable).delete()
        db.session.query(IndiAllSkyDbStarTrailsVideoTable).delete()
        db.session.query(IndiAllSkyDbPanoramaVideoTable).delete()
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="11111111-1111-1111-1111-111111111111",
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
            width=1920,
            height=1080,
            pixelSize=2.4,
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={'WEBSITE': {'TITLE': 'indi-allsky'}, 'IMAGE_FILE_TYPE': 'jpg'},
            level="1.0",
            note='test',
        )
        db.session.add(config_entry)

        # Seed image records
        img = IndiAllSkyDbImageTable(
            id=1,
            camera_id=1,
            filename="image1.jpg",
            thumbnail_uuid="thumb-uuid-1",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
            adu=1000.0,
            night=True,
        )
        db.session.add(img)

        thumb = IndiAllSkyDbThumbnailTable(
            id=1,
            camera_id=1,
            uuid="thumb-uuid-1",
            filename="thumb1.jpg",
            createDate=datetime.now(),
        )
        db.session.add(thumb)

        keogram = IndiAllSkyDbKeogramTable(
            id=1,
            camera_id=1,
            filename="keogram1.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(keogram)

        startrail = IndiAllSkyDbStarTrailsTable(
            id=1,
            camera_id=1,
            filename="startrail1.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(startrail)

        pano = IndiAllSkyDbPanoramaImageTable(
            id=1,
            camera_id=1,
            filename="pano1.jpg",
            createDate=datetime.now(),
            dayDate=datetime.now().date(),
            exposure=1.0,
            gain=100.0,
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

        video = IndiAllSkyDbVideoTable(
            id=1,
            camera_id=1,
            filename="video1.mp4",
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(video)

        startrail_vid = IndiAllSkyDbStarTrailsVideoTable(
            id=1,
            camera_id=1,
            filename="startrail1.mp4",
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(startrail_vid)

        pano_vid = IndiAllSkyDbPanoramaVideoTable(
            id=1,
            camera_id=1,
            filename="pano1.mp4",
            dayDate=datetime.now().date(),
            night=True,
        )
        db.session.add(pano_vid)

        db.session.commit()
        yield
        db.session.remove()


def test_image_redirect_views(flask_app, redirect_db):
    client = flask_app.test_client()

    # Latest image redirect with and without camera_id & night filter
    with patch.object(IndiAllSkyDbImageTable, 'getUrl', return_value='/static/image1.jpg'):
        res = client.get('/indi-allsky/latestimage?camera_id=1')
        assert res.status_code == 302

        res2 = client.get('/indi-allsky/latestimage?camera_id=1&night=1')
        assert res2.status_code == 302

    # Latest keogram redirect
    with patch.object(IndiAllSkyDbKeogramTable, 'getUrl', return_value='/static/keogram1.jpg'):
        res = client.get('/indi-allsky/latestkeogram?camera_id=1')
        assert res.status_code == 302

    # Latest startrail redirect
    with patch.object(IndiAllSkyDbStarTrailsTable, 'getUrl', return_value='/static/startrail1.jpg'):
        res = client.get('/indi-allsky/lateststartrail?camera_id=1')
        assert res.status_code == 302

    # Latest panorama image redirect
    with patch.object(IndiAllSkyDbPanoramaImageTable, 'getUrl', return_value='/static/pano1.jpg'):
        res = client.get('/indi-allsky/latestpanorama?camera_id=1')
        assert res.status_code == 302

    # Latest raw image redirect
    with patch.object(IndiAllSkyDbRawImageTable, 'getUrl', return_value='/static/raw1.raw'):
        res = client.get('/indi-allsky/latestraw?camera_id=1')
        assert res.status_code == 302

    # Latest thumbnail redirect
    with patch.object(IndiAllSkyDbThumbnailTable, 'getUrl', return_value='/static/thumb1.jpg'):
        res = client.get('/indi-allsky/latestthumbnail?camera_id=1')
        assert res.status_code == 302


def test_video_redirect_views(flask_app, redirect_db):
    client = flask_app.test_client()

    with patch.object(IndiAllSkyDbVideoTable, 'getUrl', return_value='/static/video1.mp4'):
        res = client.get('/indi-allsky/latesttimelapse?camera_id=1')
        assert res.status_code == 302

        res2 = client.get('/indi-allsky/latesttimelapse?camera_id=1&night=1')
        assert res2.status_code == 302

    with patch.object(IndiAllSkyDbStarTrailsVideoTable, 'getUrl', return_value='/static/startrail1.mp4'):
        res = client.get('/indi-allsky/lateststartrailvideo?camera_id=1')
        assert res.status_code == 302

    with patch.object(IndiAllSkyDbPanoramaVideoTable, 'getUrl', return_value='/static/pano1.mp4'):
        res = client.get('/indi-allsky/latestpanoramavideo?camera_id=1')
        assert res.status_code == 302


def test_image_view_redirects(flask_app, redirect_db):
    client = flask_app.test_client()

    res = client.get('/indi-allsky/latestimageview?camera_id=1')
    assert res.status_code == 302

    res_keogram = client.get('/indi-allsky/latestkeogramview?camera_id=1')
    assert res_keogram.status_code == 302

    res_startrail = client.get('/indi-allsky/lateststartrailview?camera_id=1')
    assert res_startrail.status_code == 302

    res_pano = client.get('/indi-allsky/latestpanoramaview?camera_id=1')
    assert res_pano.status_code == 302

    res_raw = client.get('/indi-allsky/latestrawview?camera_id=1')
    assert res_raw.status_code == 302


def test_video_watch_redirects(flask_app, redirect_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/latesttimelapsewatch?camera_id=1')
    assert res.status_code == 302

    res_startrail = client.get('/indi-allsky/lateststartrailvideowatch?camera_id=1')
    assert res_startrail.status_code == 302

    res_pano = client.get('/indi-allsky/latestpanoramavideowatch?camera_id=1')
    assert res_pano.status_code == 302


def test_panorama_and_raw_canvas_and_json_views(flask_app, redirect_db):
    client = flask_app.test_client()

    # Panorama Canvas & Img & Json
    res_pc = client.get('/indi-allsky/panorama_canvas?camera_id=1')
    assert res_pc.status_code == 200

    res_pi = client.get('/indi-allsky/panorama_img?camera_id=1')
    assert res_pi.status_code == 200

    res_pj = client.get('/indi-allsky/js/latest_panorama?camera_id=1')
    assert res_pj.status_code == 200

    # Raw Canvas & Img & Json
    res_rc = client.get('/indi-allsky/raw_canvas?camera_id=1')
    assert res_rc.status_code == 200

    res_ri = client.get('/indi-allsky/raw_img?camera_id=1')
    assert res_ri.status_code == 200

    res_rj = client.get('/indi-allsky/js/latest_rawimage?camera_id=1')
    assert res_rj.status_code == 200


def test_public_index_view(flask_app, redirect_db):
    client = flask_app.test_client()
    res = client.get('/indi-allsky/public?camera_id=1')
    assert res.status_code == 302


def test_media_redirects_extra_branches(flask_app, redirect_db):
    client = flask_app.test_client()

    # 1. Night filter parameter on image view redirects
    res_night = client.get('/indi-allsky/latestimageview?camera_id=1&night=1')
    assert res_night.status_code == 302

    # 2. web_nonlocal_images in LatestImageRedirect & LatestTimelapseVideoRedirect
    with flask_app.app_context():
        cam = db.session.get(IndiAllSkyDbCameraTable, 1)
        cam.web_nonlocal_images = True
        db.session.commit()

    with patch.object(IndiAllSkyDbImageTable, 'getUrl', return_value='/static/image1.jpg'):
        res = client.get('/indi-allsky/latestimage?camera_id=1')
        assert res.status_code == 302

    with patch.object(IndiAllSkyDbVideoTable, 'getUrl', return_value='/static/video1.mp4'):
        res_v = client.get('/indi-allsky/latesttimelapse?camera_id=1')
        assert res_v.status_code == 302

