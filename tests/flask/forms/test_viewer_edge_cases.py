"""Edge case tests for image, FITS, gallery, video, and minivideo viewers."""
from datetime import datetime

import pytest

from indi_allsky.flask import forms as f_mod
from indi_allsky.flask import db as _db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbThumbnailTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbRawImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
)


@pytest.fixture
def g12_cam_and_data(flask_app, db):
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable(
            name='g12_cam', uuid='g12-cam-uuid', friendlyName='G12 Cam',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(cam)
        db.session.commit()

        now = datetime(2026, 6, 15, 12, 0, 0)

        img_no_detection = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='no_detect_img.jpg',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            detections=0,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add(img_no_detection)

        img_remote = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='remote_img2.jpg',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            detections=0,
            remote_url='http://example.com/img2.jpg',
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        db.session.add(img_remote)

        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename='pano.jpg',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            night=True,
            exposure=1.0,
            gain=100.0,
        )
        db.session.add(pano)

        fits_diagnostic = IndiAllSkyDbFitsImageTable(
            camera_id=cam.id,
            filename='diag.fits',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            data={
                'asi676mc_diagnostic': {
                    'roles': [{'role': 'bad', 'capture_id': 'cap-001'}],
                }
            },
        )
        db.session.add(fits_diagnostic)

        raw = IndiAllSkyDbRawImageTable(
            camera_id=cam.id,
            filename='raw.cr2',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            night=True,
            exposure=1.0,
            gain=100.0,
        )
        db.session.add(raw)

        vid_day = IndiAllSkyDbVideoTable(
            camera_id=cam.id,
            filename='day_vid.mp4',
            createDate=now,
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=False,
            success=True,
        )
        db.session.add(vid_day)

        vid_night = IndiAllSkyDbVideoTable(
            camera_id=cam.id,
            filename='night_vid.mp4',
            createDate=now,
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=True,
            success=True,
        )
        db.session.add(vid_night)

        mvid = IndiAllSkyDbMiniVideoTable(
            camera_id=cam.id,
            filename='mvid.mp4',
            createDate=now,
            targetDate=now,
            startDate=now,
            endDate=now,
            note='test',
            dayDate=now.date(),
            dayDate_year=now.year,
            dayDate_month=now.month,
            dayDate_day=now.day,
            night=True,
        )
        db.session.add(mvid)

        db.session.commit()
        return cam.id, now


def test_image_viewer_no_detections(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        iv = f_mod.IndiAllskyImageViewer(camera_id=cam_id, local=True, detections_count=0)
        imgs = iv.getImages(now.year, now.month, now.day, now.hour)
        assert isinstance(imgs, list)


def test_image_viewer_no_fits_raises_no_result(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        cam_no_fits = IndiAllSkyDbCameraTable(
            name='no_fits_cam', uuid='no-fits-cam-uuid', friendlyName='No FITS Cam',
            latitude=0.0, longitude=0.0, local=True,
        )
        _db.session.add(cam_no_fits)
        _db.session.commit()

        img_no_fits = IndiAllSkyDbImageTable(
            camera_id=cam_no_fits.id,
            filename='img_no_fits.jpg',
            createDate=now,
            createDate_year=now.year,
            createDate_month=now.month,
            createDate_day=now.day,
            createDate_hour=now.hour,
            dayDate=now.date(),
            detections=0,
            exposure=1.0,
            gain=100.0,
            adu=100.0,
        )
        _db.session.add(img_no_fits)
        _db.session.commit()

        iv = f_mod.IndiAllskyImageViewer(camera_id=cam_no_fits.id, local=True, detections_count=0)
        imgs = iv.getImages(now.year, now.month, now.day, now.hour)
        assert any(d.get('fits') is None for d in imgs)


def test_image_viewer_no_images_preload(flask_app, db):
    with flask_app.test_request_context():
        empty_cam = IndiAllSkyDbCameraTable(
            name='preload_empty_cam', uuid='preload-empty-uuid', friendlyName='Preload Empty',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(empty_cam)
        db.session.commit()

        preload = f_mod.IndiAllskyImageViewerPreload(camera_id=empty_cam.id, local=True)
        assert ('', 'None') in preload.YEAR_SELECT.choices


def test_image_viewer_diagnostic_enabled(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        iv = f_mod.IndiAllskyImageViewer(
            camera_id=cam_id, local=True, detections_count=0,
            asi676mc_diagnostic_download_enabled=True,
        )
        imgs = iv.getImages(now.year, now.month, now.day, now.hour)
        assert isinstance(imgs, list)


def test_fits_image_viewer_diagnostic_role_names(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        fv = f_mod.IndiAllskyFitsImageViewer(camera_id=cam_id)
        imgs = fv.getImages(now.year, now.month, now.day, now.hour)
        assert isinstance(imgs, list)


def test_fits_image_viewer_no_images_preload(flask_app, db):
    with flask_app.test_request_context():
        empty_cam = IndiAllSkyDbCameraTable(
            name='fits_preload_empty', uuid='fits-preload-empty-uuid', friendlyName='FITS Preload Empty',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(empty_cam)
        db.session.commit()

        preload = f_mod.IndiAllskyFitsImageViewerPreload(camera_id=empty_cam.id)
        assert ('', 'None') in preload.YEAR_SELECT.choices


def test_gallery_viewer_asi676mc_status_filter(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        thumb = IndiAllSkyDbThumbnailTable(
            camera_id=cam_id,
            uuid='g12-thumb-uuid',
            filename='g12_thumb.jpg',
            createDate=now,
        )
        _db.session.add(thumb)
        _db.session.commit()

        gv = f_mod.IndiAllskyGalleryViewer(
            camera_id=cam_id, local=False,
            asi676mc_statuses=('repair_complete',),
        )
        years = gv.getYears()
        assert isinstance(years, list)
        months = gv.getMonths(now.year)
        assert isinstance(months, list)
        days = gv.getDays(now.year, now.month)
        assert isinstance(days, list)
        hours = gv.getHours(now.year, now.month, now.day)
        assert isinstance(hours, list)
        imgs = gv.getImages(now.year, now.month, now.day, now.hour)
        assert isinstance(imgs, list)


def test_gallery_viewer_no_images_preload(flask_app, db):
    with flask_app.test_request_context():
        empty_cam = IndiAllSkyDbCameraTable(
            name='gallery_preload_empty', uuid='gallery-preload-empty-uuid', friendlyName='Gallery Preload Empty',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(empty_cam)
        db.session.commit()

        preload = f_mod.IndiAllskyGalleryViewerPreload(camera_id=empty_cam.id, local=True)
        assert ('', 'None') in preload.YEAR_SELECT.choices


def test_video_viewer_timeofday_day(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=True)
        videos = vv.getVideos(now.year, now.month, 'day')
        assert isinstance(videos, list)


def test_video_viewer_timeofday_night(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=True)
        videos = vv.getVideos(now.year, now.month, 'night')
        assert isinstance(videos, list)


def test_video_viewer_remote_filter(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        vv = f_mod.IndiAllskyVideoViewer(camera_id=cam_id, local=False)
        years = vv.getYears()
        assert isinstance(years, list)
        months = vv.getMonths(now.year)
        assert isinstance(months, list)
        videos = vv.getVideos(now.year, now.month, 'all')
        assert isinstance(videos, list)


def test_video_viewer_no_videos_preload(flask_app, db):
    with flask_app.test_request_context():
        empty_cam = IndiAllSkyDbCameraTable(
            name='video_preload_empty', uuid='video-preload-empty-uuid', friendlyName='Video Preload Empty',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(empty_cam)
        db.session.commit()

        preload = f_mod.IndiAllskyVideoViewerPreload(camera_id=empty_cam.id, local=True)
        assert ('', 'None') in preload.YEAR_SELECT.choices


def test_minivideo_viewer_remote_filter(flask_app, g12_cam_and_data):
    cam_id, now = g12_cam_and_data
    with flask_app.test_request_context():
        mv = f_mod.IndiAllskyMiniVideoViewer(camera_id=cam_id, local=False)
        years = mv.getYears()
        assert isinstance(years, list)
        months = mv.getMonths(now.year)
        assert isinstance(months, list)
        videos = mv.getVideos(now.year, now.month)
        assert isinstance(videos, list)


def test_minivideo_viewer_no_videos_preload(flask_app, db):
    with flask_app.test_request_context():
        empty_cam = IndiAllSkyDbCameraTable(
            name='mvideo_preload_empty', uuid='mvideo-preload-empty-uuid', friendlyName='MVideo Preload Empty',
            latitude=0.0, longitude=0.0, local=True,
        )
        db.session.add(empty_cam)
        db.session.commit()

        preload = f_mod.IndiAllskyMiniVideoViewerPreload(camera_id=empty_cam.id, local=True)
        assert ('', 'None') in preload.YEAR_SELECT.choices
