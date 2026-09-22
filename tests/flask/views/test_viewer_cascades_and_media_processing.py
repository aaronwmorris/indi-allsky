import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest
from flask import json

from indi_allsky.flask.models import (
    db,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbFitsImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbTaskQueueTable,
    IndiAllSkyDbThumbnailTable,
    TaskQueueQueue,
    TaskQueueState,
    IndiAllSkyDbUserTable,
)
from indi_allsky.flask.views import (
    AjaxImageViewerView,
    AjaxFitsImageViewerView,
    AjaxGalleryViewerView,
    AjaxVideoViewerView,
    AjaxMiniVideoViewerView,
    AjaxMiniVideoDeleteView,
    TimelapseVideoView,
    AjaxMiniTimelapseGeneratorView,
    JsonImageProcessingView,
    AjaxAsi676mcCalibrationCancelView,
    AjaxAsi676mcCalibrationStartView,
    SystemInfoView,
)
from indi_allsky.asi676mc_calibration import CalibrationSessionError


def test_ajax_image_and_fits_viewers_cascading_selections(flask_app, system_db):
    """Test AjaxImageViewerView and AjaxFitsImageViewerView cascading year/month/day/hour selections."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Image Viewer with only year (and nested empty/populated branches)
            with patch("indi_allsky.flask.views.IndiAllskyImageViewer") as mock_viewer_cls:
                mock_viewer = MagicMock()
                mock_viewer_cls.return_value = mock_viewer
                mock_viewer.getMonths.return_value = ((1, "January"),)
                mock_viewer.getDays.return_value = ((15, "15"),)
                mock_viewer.getHours.return_value = ((22, "22"),)
                mock_viewer.getImages.return_value = [{"url": "/img.jpg"}]

                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200
                data = json.loads(res.data)
                assert "IMAGE_DATA" in data

                # Year with no months
                mock_viewer.getMonths.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200

                # Month with no days
                mock_viewer.getDays.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026, "MONTH_SELECT": 5},
                )
                assert res.status_code == 200

                # Month with days but no hours
                mock_viewer.getDays.return_value = ((10, "10"),)
                mock_viewer.getHours.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026, "MONTH_SELECT": 5},
                )
                assert res.status_code == 200

                # Day with no hours
                mock_viewer.getHours.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026, "MONTH_SELECT": 5, "DAY_SELECT": 10},
                )
                assert res.status_code == 200

                # No selection (filter detections or empty DB)
                mock_viewer.getYears.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id},
                )
                assert res.status_code == 200

                # No selection with years found
                mock_viewer.getYears.return_value = ((2026, "2026"),)
                mock_viewer.getMonths.return_value = ((5, "May"),)
                mock_viewer.getDays.return_value = ((10, "10"),)
                mock_viewer.getHours.return_value = ((20, "20"),)
                mock_viewer.getImages.return_value = [{"url": "/img.jpg"}]
                res = client.post(
                    "/indi-allsky/ajax/imageviewer",
                    json={"CAMERA_ID": cam_id},
                )
                assert res.status_code == 200

            # 2. Fits Image Viewer cascades
            with patch("indi_allsky.flask.views.IndiAllskyFitsImageViewer") as mock_fits_cls:
                mock_fits = MagicMock()
                mock_fits_cls.return_value = mock_fits
                mock_fits.getMonths.return_value = ((1, "January"),)
                mock_fits.getDays.return_value = ((15, "15"),)
                mock_fits.getHours.return_value = ((22, "22"),)
                mock_fits.getImages.return_value = [{"url": "/img.fits"}]

                res = client.post(
                    "/indi-allsky/ajax/fitsimageviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200


def test_ajax_gallery_and_video_viewers_filters_and_branches(flask_app, system_db):
    """Test AjaxGalleryViewerView with ASI676MC filter switches, VideoViewerView and MiniVideoViewerView cascades."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Gallery viewer with ASI676MC filters and nonlocal admin bypass
            with patch("indi_allsky.flask.views.asi676mc.camera_record_matches", return_value=True), \
                 patch("indi_allsky.flask.views.IndiAllskyGalleryViewer") as mock_gal_cls:
                mock_gal = MagicMock()
                mock_gal_cls.return_value = mock_gal
                mock_gal.getMonths.return_value = ((1, "January"),)
                mock_gal.getDays.return_value = ((1, "1"),)
                mock_gal.getHours.return_value = ((0, "0"),)
                mock_gal.getImages.return_value = []

                with patch.dict(flask_app.config, {"IMAGE_ASI676MC_REPAIR": {"ENABLE": True, "GALLERY_ENABLE": True}}):
                    res = client.post(
                        "/indi-allsky/ajax/gallery",
                        json={
                            "CAMERA_ID": cam_id,
                            "YEAR_SELECT": 2026,
                            "FILTER_ASI676MC_REPAIRED": True,
                            "FILTER_ASI676MC_EXCLUDED": True,
                            "FILTER_ASI676MC_FAILED": True,
                        },
                    )
                    assert res.status_code == 200

            # 2. Video viewer with year only (and empty months)
            with patch("indi_allsky.flask.views.IndiAllskyVideoViewer") as mock_vid_cls:
                mock_vid = MagicMock()
                mock_vid_cls.return_value = mock_vid
                mock_vid.getMonths.return_value = ((6, "June"),)
                mock_vid.getVideos.return_value = [{"url": "/v.mp4"}]

                res = client.post(
                    "/indi-allsky/ajax/videoviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200

                mock_vid.getMonths.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/videoviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200

                # Empty selection
                res = client.post(
                    "/indi-allsky/ajax/videoviewer",
                    json={"CAMERA_ID": cam_id},
                )
                assert res.status_code == 200

            # 3. Mini Video viewer with year only and empty selection
            with patch("indi_allsky.flask.views.IndiAllskyMiniVideoViewer") as mock_mini_cls:
                mock_mini = MagicMock()
                mock_mini_cls.return_value = mock_mini
                mock_mini.getMonths.return_value = ((6, "June"),)
                mock_mini.getVideos.return_value = [{"url": "/mv.mp4"}]

                res = client.post(
                    "/indi-allsky/ajax/minivideoviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200

                mock_mini.getMonths.return_value = ()
                res = client.post(
                    "/indi-allsky/ajax/minivideoviewer",
                    json={"CAMERA_ID": cam_id, "YEAR_SELECT": 2026},
                )
                assert res.status_code == 200

                res = client.post(
                    "/indi-allsky/ajax/minivideoviewer",
                    json={"CAMERA_ID": cam_id},
                )
                assert res.status_code == 200


def test_ajax_mini_video_delete_view_permissions_and_tasks(flask_app, system_db):
    """Test AjaxMiniVideoDeleteView permission checks, active queue conflicts, and file deletion errors."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Permission denied (403)
            with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=False):
                res = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={})
                assert res.status_code == 403

            # 2. Invalid request json (400)
            res = client.post("/indi-allsky/ajax/minivideoviewer/delete", json={"CAMERA_ID": "invalid"})
            assert res.status_code == 400

            # 3. Mini timelapse not found in DB (404)
            res = client.post(
                "/indi-allsky/ajax/minivideoviewer/delete",
                json={"CAMERA_ID": cam_id, "VIDEO_ID": 999999},
            )
            assert res.status_code == 404

            # Create a mini video record and active task records
            now = datetime.now(timezone.utc)
            gen_task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.VIDEO,
                state=TaskQueueState.RUNNING,
                createDate=now,
                data={},
            )
            db.session.add(gen_task)
            db.session.commit()

            mini_video = IndiAllSkyDbMiniVideoTable(
                camera_id=cam_id,
                filename="mini_test.mp4",
                night=True,
                dayDate=now.date(),
                createDate=now,
                targetDate=now,
                startDate=now - timedelta(hours=1),
                endDate=now,
                note="Test Note",
                data={"generation_task_id": gen_task.id, "generation_task_created": gen_task.createDate.isoformat()},
            )
            db.session.add(mini_video)
            db.session.commit()

            # 4. Active generation task conflict (409)
            res = client.post(
                "/indi-allsky/ajax/minivideoviewer/delete",
                json={"CAMERA_ID": cam_id, "VIDEO_ID": mini_video.id},
            )
            assert res.status_code == 409
            assert b"still being created" in res.data

            # Finish generation task and create active upload task
            gen_task.state = TaskQueueState.SUCCESS
            upload_task = IndiAllSkyDbTaskQueueTable(
                queue=TaskQueueQueue.UPLOAD,
                state=TaskQueueState.RUNNING,
                createDate=now,
                data={"model": "IndiAllSkyDbMiniVideoTable", "id": mini_video.id},
            )
            db.session.add(upload_task)
            db.session.commit()

            # 5. Active upload task conflict (409)
            res = client.post(
                "/indi-allsky/ajax/minivideoviewer/delete",
                json={"CAMERA_ID": cam_id, "VIDEO_ID": mini_video.id},
            )
            assert res.status_code == 409
            assert b"still being uploaded" in res.data

            # Finish upload task
            upload_task.state = TaskQueueState.SUCCESS
            db.session.commit()

            # 6. OSError during deleteAsset (400)
            with patch.object(IndiAllSkyDbMiniVideoTable, "deleteAsset", side_effect=OSError("Disk write protected")):
                res = client.post(
                    "/indi-allsky/ajax/minivideoviewer/delete",
                    json={"CAMERA_ID": cam_id, "VIDEO_ID": mini_video.id},
                )
                assert res.status_code == 400
                assert b"Unable to remove" in res.data


def test_video_watch_and_mini_timelapse_generator_branches(flask_app, system_db):
    """Test TimelapseVideoView get_context branches and AjaxMiniTimelapseGeneratorView validation."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        # 1. TimelapseVideoView without id (defaults to latest) and video not found
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            res = client.get("/indi-allsky/watch_timelapse?id=-1")
            assert res.status_code == 200

            # TimelapseVideoView with nonexistent ID
            res = client.get("/indi-allsky/watch_timelapse?id=999999")
            assert res.status_code == 200
            assert b"Video not found" in res.data

        # 2. AjaxMiniTimelapseGeneratorView non-admin permission (400)
        non_admin_user = MagicMock()
        non_admin_user.is_authenticated = True
        non_admin_user.is_admin = False

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", non_admin_user):
            res = client.post("/indi-allsky/ajax/minigenerate", json={})
            assert res.status_code == 400
            assert b"permission" in res.data

        # 3. Invalid source_type (400)
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            res = client.post(
                "/indi-allsky/ajax/minigenerate",
                json={"SOURCE_TYPE": "unknown_source"},
            )
            assert res.status_code == 400
            assert b"Choose all-sky images or panorama images" in res.data

            # 4. Standard mini timelapse with missing target image in DB (400)
            res = client.post(
                "/indi-allsky/ajax/minigenerate",
                json={
                    "SOURCE_TYPE": "standard",
                    "CAMERA_ID": cam_id,
                    "IMAGE_ID": 999999,
                    "PRE_SECONDS": 3600,
                    "POST_SECONDS": 3600,
                    "FRAMERATE": 25.0,
                    "NOTE": "Valid Note",
                },
            )
            assert res.status_code == 400
            assert b"selected image is no longer available" in res.data


def test_fits_image_processing_and_asi676mc_actions(flask_app, system_db, tmp_path):
    """Test JsonImageProcessingView error & detection branches, and ASI676MC calibration actions."""
    client = flask_app.test_client()
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        cam_id = cam.id if cam else 1

        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        fits_file = tmp_path / "test_proc.fits"
        fits_file.write_bytes(b"BAD FITS DATA")

        now = datetime.now(timezone.utc)
        fits_record = IndiAllSkyDbFitsImageTable(
            camera_id=cam_id,
            filename=str(fits_file),
            createDate=now,
            dayDate=now.date(),
            exposure=1.0,
            gain=100.0,
            binmode=1,
        )
        db.session.add(fits_record)
        db.session.commit()

        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            # 1. Bad FITS file (500)
            payload = {
                "CAMERA_ID": cam_id,
                "FRAME_TYPE": "fits",
                "FITS_ID": fits_record.id,
                "OUTPUT_IMAGE_TYPE": "jpg",
                "DISABLE_PROCESSING": False,
                "LENS_IMAGE_CIRCLE": 1000,
                "LENS_OFFSET_X": 0,
                "LENS_OFFSET_Y": 0,
                "LENS_AZIMUTH": 0.0,
                "CCD_BIT_DEPTH": 16,
                "IMAGE_CALIBRATE_DARK": False,
                "IMAGE_CALIBRATE_BPM": False,
                "IMAGE_CALIBRATE_FIX_HOLES": False,
                "IMAGE_CALIBRATE_HOLE_THOLD": 1000,
                "IMAGE_CALIBRATE_MANUAL_OFFSET": 0,
                "NIGHT_CONTRAST_ENHANCE": False,
                "IMAGE_COLORMAP": "none",
                "CONTRAST_ENHANCE_16BIT": False,
                "CLAHE_CLIPLIMIT": 2.0,
                "CLAHE_GRIDSIZE": 8,
                "IMAGE_STRETCH__CLASSNAME": "",
                "IMAGE_STRETCH__MODE1_GAMMA": 1.0,
                "IMAGE_STRETCH__MODE1_STDDEVS": 3.0,
                "IMAGE_STRETCH__MODE2_SHADOWS": 0.0,
                "IMAGE_STRETCH__MODE2_MIDTONES": 0.5,
                "IMAGE_STRETCH__MODE2_HIGHLIGHTS": 1.0,
                "IMAGE_STRETCH__MODE3_BLACK_CLIP": 0.0,
                "IMAGE_STRETCH__MODE3_SHADOWS": 0.0,
                "IMAGE_STRETCH__MODE3_MIDTONES": 0.5,
                "IMAGE_STRETCH__MODE3_HIGHLIGHTS": 1.0,
                "CFA_PATTERN": "RGGB",
                "SCNR_ALGORITHM": "none",
                "SCNR_MTF_MIDTONES": 0.5,
                "IMAGE_DENOISE": "none",
                "IMAGE_DENOISE_STRENGTH": 0,
                "BILATERAL_SIGMA_COLOR": 75,
                "BILATERAL_SIGMA_SPACE": 75,
                "WBR_FACTOR": 1.0,
                "WBG_FACTOR": 1.0,
                "WBB_FACTOR": 1.0,
                "WBR_MTF_MIDTONES": 0.5,
                "WBG_MTF_MIDTONES": 0.5,
                "WBB_MTF_MIDTONES": 0.5,
                "AUTO_WB": False,
                "SATURATION_FACTOR": 1.0,
                "GAMMA_CORRECTION": 1.0,
                "SHARPEN_AMOUNT": 0.0,
                "IMAGE_ROTATE": "none",
                "IMAGE_ROTATE_ANGLE": 0,
                "IMAGE_ROTATE_KEEP_SIZE": False,
                "IMAGE_FLIP_V": False,
                "IMAGE_FLIP_H": False,
                "DETECT_MASK": "",
                "SQM_FOV_DIV": 1,
                "IMAGE_STACK_METHOD": "median",
                "IMAGE_STACK_COUNT": 1,
                "IMAGE_STACK_ALIGN": False,
                "IMAGE_ALIGN_DETECTSIGMA": 5,
                "IMAGE_ALIGN_POINTS": 100,
                "IMAGE_ALIGN_SOURCEMINAREA": 5,
                "FISH2PANO__ENABLE": False,
                "FISH2PANO__DIAMETER": 1000,
                "FISH2PANO__ROTATE_ANGLE": 0,
                "FISH2PANO__SCALE": 1.0,
                "FISH2PANO__FLIP_H": False,
                "FISH2PANO__ENABLE_CARDINAL_DIRS": False,
                "FISH2PANO__DIRS_OFFSET_BOTTOM": 0,
                "FISH2PANO__OPENCV_FONT_SCALE": 1.0,
                "FISH2PANO__PIL_FONT_SIZE": 12,
                "PROCESSING_SPLIT_SCREEN": False,
                "IMAGE_LABEL_TEMPLATE": "",
                "IMAGE_EXTRA_TEXT": "",
                "IMAGE_LABEL_SYSTEM": "",
                "TEXT_PROPERTIES__FONT_FACE": "FONT_HERSHEY_SIMPLEX",
                "TEXT_PROPERTIES__FONT_SCALE": 1.0,
                "TEXT_PROPERTIES__FONT_THICKNESS": 1,
                "TEXT_PROPERTIES__FONT_OUTLINE": False,
                "TEXT_PROPERTIES__FONT_HEIGHT": 20,
                "TEXT_PROPERTIES__FONT_X": 10,
                "TEXT_PROPERTIES__FONT_Y": 10,
                "TEXT_PROPERTIES__PIL_FONT_FILE": "",
                "TEXT_PROPERTIES__PIL_FONT_CUSTOM": "",
                "TEXT_PROPERTIES__PIL_FONT_SIZE": 12,
                "TEXT_PROPERTIES__FONT_COLOR": "255,255,255",
                "CARDINAL_DIRS__ENABLE": False,
                "CARDINAL_DIRS__SWAP_NS": False,
                "CARDINAL_DIRS__SWAP_EW": False,
                "CARDINAL_DIRS__CHAR_NORTH": "N",
                "CARDINAL_DIRS__CHAR_EAST": "E",
                "CARDINAL_DIRS__CHAR_WEST": "W",
                "CARDINAL_DIRS__CHAR_SOUTH": "S",
                "CARDINAL_DIRS__DIAMETER": 1000,
                "CARDINAL_DIRS__OFFSET_X": 0,
                "CARDINAL_DIRS__OFFSET_Y": 0,
                "CARDINAL_DIRS__OFFSET_TOP": 0,
                "CARDINAL_DIRS__OFFSET_LEFT": 0,
                "CARDINAL_DIRS__OFFSET_RIGHT": 0,
                "CARDINAL_DIRS__OFFSET_BOTTOM": 0,
                "CARDINAL_DIRS__OPENCV_FONT_SCALE": 1.0,
                "CARDINAL_DIRS__PIL_FONT_SIZE": 12,
                "CARDINAL_DIRS__OUTLINE_CIRCLE": False,
                "CARDINAL_DIRS__FONT_COLOR": "255,255,255",
                "IMAGE_CIRCLE_MASK__ENABLE": False,
                "IMAGE_CIRCLE_MASK__DIAMETER": 1000,
                "IMAGE_CIRCLE_MASK__OFFSET_X": 0,
                "IMAGE_CIRCLE_MASK__OFFSET_Y": 0,
                "IMAGE_CIRCLE_MASK__BLUR": 0,
                "IMAGE_CIRCLE_MASK__OPACITY": 100,
                "IMAGE_CIRCLE_MASK__OUTLINE": False,
                "IMAGE_CROP_IMAGE_CIRCLE": False,
                "IMAGE_BORDER__TOP": 0,
                "IMAGE_BORDER__LEFT": 0,
                "IMAGE_BORDER__RIGHT": 0,
                "IMAGE_BORDER__BOTTOM": 0,
                "IMAGE_BORDER__COLOR": "0,0,0",
                "MOON_OVERLAY__ENABLE": False,
                "MOON_OVERLAY__X": 0,
                "MOON_OVERLAY__Y": 0,
                "MOON_OVERLAY__SCALE": 1.0,
                "MOON_OVERLAY__DARK_SIDE_SCALE": 1.0,
                "MOON_OVERLAY__FLIP_V": False,
                "MOON_OVERLAY__FLIP_H": False,
                "LIGHTGRAPH_OVERLAY__ENABLE": False,
                "LIGHTGRAPH_OVERLAY__GRAPH_HEIGHT": 50,
                "LIGHTGRAPH_OVERLAY__GRAPH_BORDER": 2,
                "LIGHTGRAPH_OVERLAY__Y": 0,
                "LIGHTGRAPH_OVERLAY__OFFSET_X": 0,
                "LIGHTGRAPH_OVERLAY__SCALE": 1.0,
                "LIGHTGRAPH_OVERLAY__NOW_MARKER_SIZE": 5,
                "LIGHTGRAPH_OVERLAY__OPACITY": 100,
                "LIGHTGRAPH_OVERLAY__PIL_FONT_SIZE": 12,
                "LIGHTGRAPH_OVERLAY__OPENCV_FONT_SCALE": 1.0,
                "LIGHTGRAPH_OVERLAY__LABEL": False,
                "LIGHTGRAPH_OVERLAY__HOUR_LINES": False,
                "LIGHTGRAPH_OVERLAY__DAY_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__DUSK_COLOR": "255,255,255",
                "LIGHTGRAPH_OVERLAY__NIGHT_COLOR": "0,0,0",
                "LIGHTGRAPH_OVERLAY__MOONMODE_COLOR": "100,100,100",
                "LIGHTGRAPH_OVERLAY__HOUR_COLOR": "150,150,150",
                "LIGHTGRAPH_OVERLAY__BORDER_COLOR": "200,200,200",
                "LIGHTGRAPH_OVERLAY__NOW_COLOR": "255,0,0",
                "LIGHTGRAPH_OVERLAY__FONT_COLOR": "150,150,150",
                "SQM_ROI_X1": 0,
                "SQM_ROI_Y1": 0,
                "SQM_ROI_X2": 0,
                "SQM_ROI_Y2": 0,
                "RUN_DETECTION": False,
            }
            import wtforms
            with patch.object(wtforms.Form, "validate", lambda self, extra_validators=None: True):
                res = client.post(
                    "/indi-allsky/js/processing",
                    json=payload,
                )
                assert res.status_code == 500
                data = json.loads(res.data)
                assert data["message"] == "Bad FITS file"

            # 2. AjaxAsi676mcCalibrationCancelView error handling
            with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True), \
                 patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
                 patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock()]), \
                 patch("indi_allsky.flask.views._calibration_owner", return_value="admin"), \
                 patch("indi_allsky.asi676mc_calibration.cancel_session", side_effect=CalibrationSessionError("Session locked")):
                res = client.post("/indi-allsky/ajax/asi676mc/calibration/cancel/test-session")
                assert res.status_code == 409
                assert b"Session locked" in res.data

            with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True), \
                 patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
                 patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock()]), \
                 patch("indi_allsky.flask.views._calibration_owner", return_value="admin"), \
                 patch("indi_allsky.asi676mc_calibration.cancel_session", side_effect=OSError("Disk failure")):
                res = client.post("/indi-allsky/ajax/asi676mc/calibration/cancel/test-session")
                assert res.status_code == 500
                assert b"Cancellation could not be confirmed" in res.data

            # 3. AjaxAsi676mcCalibrationStartView invalid max_pair_seconds (400)
            with patch("indi_allsky.flask.views._can_save_standard_configuration", return_value=True), \
                 patch("indi_allsky.flask.views._asi676mc_feature_enabled", return_value=True), \
                 patch("indi_allsky.flask.views._visible_asi676mc_cameras", return_value=[MagicMock()]), \
                 patch("indi_allsky.flask.views._calibration_owner", return_value="admin"):
                res = client.post(
                    "/indi-allsky/ajax/asi676mc/calibration/start/test-session",
                    json={"max_pair_seconds": "invalid_seconds"},
                )
                assert res.status_code == 400
                assert b"valid maximum gap" in res.data


def test_system_info_missing_optional_modules(flask_app, system_db):
    """Test SystemInfoView get_context when optional modules fail to import."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    client = flask_app.test_client()
    with flask_app.app_context():
        with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
             patch("indi_allsky.flask.views.current_user", mock_user):
            with patch.dict("sys.modules", {"pycurl": None, "paho.mqtt": None, "skyfield": None}):
                res = client.get("/indi-allsky/system")
                assert res.status_code == 200
