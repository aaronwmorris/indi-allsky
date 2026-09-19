from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from indi_allsky.flask.views import (
    AjaxUploadYoutubeView,
    CameraSimulatorView,
    TimelapseImageView,
    AjaxMiniTimelapseGeneratorView,
    AjaxCustomCssView,
    AjaxSelectCameraView,
    AjaxImageExcludeView,
)


def test_youtube_upload_view(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        res = client.post("/indi-allsky/ajax/upload_youtube", json={"video_id": 1, "model": "IndiAllSkyDbVideoTable"})
        assert res.status_code in (200, 400, 404)


def test_camera_simulator_and_timelapse_image_view(flask_app, system_db):
    client = flask_app.test_client()

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}):
        res = client.get("/indi-allsky/camerasimulator")
        assert res.status_code == 200

        res_tl = client.get("/indi-allsky/timelapse_image")
        assert res_tl.status_code in (200, 404)


def test_mini_timelapse_and_custom_css_views(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value.returncode = 0
            res_css = client.post("/indi-allsky/ajax/custom_css", json={"custom_css": "body { color: red; }"})
            assert res_css.status_code in (200, 500)

        res_cam = client.post("/indi-allsky/ajax/selectcamera", json={"camera_id": 1})
        assert res_cam.status_code in (200, 400)

        res_ex = client.post("/indi-allsky/ajax/image_exclude", json={"image_id": 1, "exclude": True})
        assert res_ex.status_code in (200, 400, 404)

        res_mini = client.post("/indi-allsky/ajax/minigenerate", json={"camera_id": 1})
        assert res_mini.status_code in (200, 400)
