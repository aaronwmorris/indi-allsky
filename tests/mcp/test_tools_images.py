"""Unit tests for MCP image catalog tools."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from datetime import datetime, date

from indi_allsky.flask import create_app
from indi_allsky.mcp.tools_images import (
    get_latest_image,
    query_image_history,
    get_raw_fits_catalog,
    get_image_metadata,
)


@pytest.fixture
def app_ctx():
    app = create_app()
    with app.app_context():
        yield app


def test_get_latest_image(app_ctx):
    mock_image = SimpleNamespace(
        id=10,
        filename="/images/test.jpg",
        createDate=datetime(2026, 9, 29, 12, 0, 0),
        dayDate=date(2026, 9, 29),
        exposure=15.0,
        gain=100.0,
        binmode=1,
        temp=18.5,
        night=True,
        adu=25.4,
        sqm=21.2,
        stars=142,
        detections=0,
        moonphase=0.25,
    )
    mock_fits = SimpleNamespace(
        id=99,
        filename="/images/test.fit",
    )

    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_img_q, \
         patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_fits_q:
        mock_img_q.filter.return_value.order_by.return_value.first.return_value = mock_image
        mock_fits_q.filter.return_value.order_by.return_value.first.return_value = mock_fits

        res = get_latest_image(camera_id=1, include_raw=True)
        assert res["status"] == "success"
        assert res["image_id"] == 10
        assert res["stars"] == 142
        assert res["latest_fits_id"] == 99


def test_query_image_history(app_ctx):
    mock_img = SimpleNamespace(
        id=1,
        filename="img1.jpg",
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        exposure=15.0,
        gain=100.0,
        binmode=1,
        temp=15.0,
        night=True,
        adu=20.0,
        sqm=21.5,
        stars=180,
        detections=1,
    )

    with patch("indi_allsky.flask.models.IndiAllSkyDbImageTable.query") as mock_q:
        mock_filter = mock_q.filter.return_value
        mock_filter.filter.return_value = mock_filter
        mock_filter.order_by.return_value.limit.return_value.all.return_value = [mock_img]

        res = query_image_history(camera_id=1, limit=10, night_only=True, min_stars=50)
        assert len(res) == 1
        assert res[0]["id"] == 1
        assert res[0]["stars"] == 180


def test_get_raw_fits_catalog(app_ctx):
    mock_fits = SimpleNamespace(
        id=101,
        filename="test.fit",
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        dayDate=date(2026, 9, 29),
        exposure=15.0,
        gain=100.0,
        binmode=1,
        night=True,
        fileSize=1048576,
    )

    with patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_q:
        mock_q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_fits]

        res = get_raw_fits_catalog(camera_id=1, limit=5)
        assert len(res) == 1
        assert res[0]["fits_id"] == 101
        assert res[0]["exposure"] == 15.0


def test_get_image_metadata(app_ctx):
    mock_fits = SimpleNamespace(
        id=101,
        filename="test.fit",
        createDate=datetime(2026, 9, 29, 2, 0, 0),
        dayDate=date(2026, 9, 29),
        exposure=15.0,
        gain=100.0,
        binmode=1,
        night=True,
        fileSize=1048576,
        width=3000,
        height=3000,
        data={"OBSERVER": "AllSky"},
    )

    with patch("indi_allsky.flask.models.IndiAllSkyDbFitsImageTable.query") as mock_q:
        mock_q.filter.return_value.first.return_value = mock_fits

        res = get_image_metadata(fits_id=101)
        assert res["status"] == "success"
        assert res["fits_id"] == 101
        assert res["width"] == 3000
        assert res["data"]["OBSERVER"] == "AllSky"
