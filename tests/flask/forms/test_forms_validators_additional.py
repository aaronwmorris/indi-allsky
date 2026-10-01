import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from indi_allsky.flask.forms import (
    ALLSKYMAP__MAP_LATITUDE_validator,
    ALLSKYMAP__MAP_LONGITUDE_validator,
    IndiAllskyFitsImageViewer,
    IndiAllskyFitsImageViewerPreload,
)

class DummyField:
    def __init__(self, data):
        self.data = data

class DummyForm:
    def __init__(self, loc_lat=None, loc_lng=None):
        self.LOCATION_LATITUDE = DummyField(loc_lat)
        self.LOCATION_LONGITUDE = DummyField(loc_lng)

def test_map_latitude_validator_out_of_range_and_invalid():
    # loc_lat out of range (-90..90)
    form = DummyForm(loc_lat='999.0')
    field = DummyField('45.0')
    ALLSKYMAP__MAP_LATITUDE_validator(form, field)

    # loc_lat raises ValueError
    form2 = DummyForm(loc_lat='not_a_float')
    ALLSKYMAP__MAP_LATITUDE_validator(form2, field)

def test_map_longitude_validator_out_of_range_and_invalid():
    # loc_lng out of range (-180..180)
    form = DummyForm(loc_lng='999.0')
    field = DummyField('45.0')
    ALLSKYMAP__MAP_LONGITUDE_validator(form, field)

    # loc_lng raises ValueError
    form2 = DummyForm(loc_lng='not_a_float')
    ALLSKYMAP__MAP_LONGITUDE_validator(form2, field)

def test_fits_image_viewer_get_images_value_error(app):
    with app.test_request_context():
        viewer = IndiAllskyFitsImageViewer(camera_id=1, local=True)
        
        mock_img = MagicMock()
        mock_img.id = 1
        mock_img.createDate = datetime.now()
        mock_img.data = {}
        mock_img.getUrl.side_effect = ValueError('Relative file path error')
        
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.count.return_value = 1
        mock_query.__iter__.return_value = iter([mock_img])
        
        with patch('indi_allsky.flask.forms.db.session.query', return_value=mock_query):
            images = viewer.getImages(2025, 1, 1, 12)
            assert len(images) == 0

def test_fits_image_viewer_preload_remote(app):
    with app.app_context():
        viewer = IndiAllskyFitsImageViewerPreload(camera_id=1, local=False)
        assert viewer.local is False
