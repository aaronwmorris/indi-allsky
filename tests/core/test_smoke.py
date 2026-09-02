import pytest
from unittest.mock import MagicMock

from indi_allsky.smoke import IndiAllskySmokeUpdate, NoSmokeData
from indi_allsky import constants


class MockCamera:
    def __init__(self, lat, lon, data=None):
        self.latitude = lat
        self.longitude = lon
        self.data = data


MOCK_KML_VALID = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Folder>
      <name>Smoke (Heavy)</name>
      <Placemark>
        <Polygon>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>
                -100.0,40.0,0
                -90.0,40.0,0
                -90.0,50.0,0
                -100.0,50.0,0
                -100.0,40.0,0
              </coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
  </Document>
</kml>"""

MOCK_KML_NO_FOLDERS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
  </Document>
</kml>"""


def test_update_north_america(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    camera = MockCamera(45.0, -95.0, data={})
    
    mocker.patch.object(smoke, 'update_na_hms', return_value=constants.SMOKE_RATING_HEAVY)
    mock_commit = mocker.patch('indi_allsky.smoke.db.session.commit')
    
    smoke.update(camera)
    
    smoke.update_na_hms.assert_called_once_with(camera)
    assert camera.data['SMOKE_RATING'] == constants.SMOKE_RATING_HEAVY
    assert 'SMOKE_DATA_TS' in camera.data
    mock_commit.assert_called_once()


def test_update_outside_north_america(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    camera = MockCamera(-33.0, 151.0, data={})
    
    mocker.patch.object(smoke, 'update_na_hms')
    mock_commit = mocker.patch('indi_allsky.smoke.db.session.commit')
    
    smoke.update(camera)
    
    smoke.update_na_hms.assert_not_called()
    assert camera.data['SMOKE_RATING'] == constants.SMOKE_RATING_NODATA
    assert 'SMOKE_DATA_TS' in camera.data
    mock_commit.assert_called_once()


def test_update_no_smoke_data_exception(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    camera = MockCamera(45.0, -95.0, data={'existing_key': 'value'})
    
    mocker.patch.object(smoke, 'update_na_hms', side_effect=NoSmokeData("Test error"))
    mock_commit = mocker.patch('indi_allsky.smoke.db.session.commit')
    
    smoke.update(camera)
    
    smoke.update_na_hms.assert_called_once_with(camera)
    assert 'SMOKE_RATING' not in camera.data
    assert camera.data == {'existing_key': 'value'}
    mock_commit.assert_not_called()


def test_update_stores_and_commits(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    camera = MockCamera(45.0, -95.0, data=None)  # Test with None data
    
    mocker.patch.object(smoke, 'update_na_hms', return_value=constants.SMOKE_RATING_LIGHT)
    mock_commit = mocker.patch('indi_allsky.smoke.db.session.commit')
    
    smoke.update(camera)
    
    assert camera.data['SMOKE_RATING'] == constants.SMOKE_RATING_LIGHT
    assert 'SMOKE_DATA_TS' in camera.data
    mock_commit.assert_called_once()


def test_download_kml_success(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "test_kml_content"
    
    mocker.patch('indi_allsky.smoke.requests.get', return_value=mock_response)
    
    result = smoke.download_kml("http://test.url")
    
    assert result == b"test_kml_content"


def test_download_kml_http_error(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    mock_response = MagicMock()
    mock_response.status_code = 404
    
    mocker.patch('indi_allsky.smoke.requests.get', return_value=mock_response)
    
    result = smoke.download_kml("http://test.url")
    
    assert result is None


def test_update_na_hms_intersects(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    smoke.hms_kml_data = MOCK_KML_VALID.encode('utf-8')
    # Point inside the polygon (-100 to -90 lon, 40 to 50 lat)
    camera = MockCamera(45.0, -95.0)
    
    mocker.patch.object(smoke, 'download_kml')
    
    rating = smoke.update_na_hms(camera)
    
    assert rating == constants.SMOKE_RATING_HEAVY
    smoke.download_kml.assert_not_called()


def test_update_na_hms_no_intersect(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    smoke.hms_kml_data = MOCK_KML_VALID.encode('utf-8')
    # Point outside the polygon (-100 to -90 lon, 40 to 50 lat)
    camera = MockCamera(35.0, -85.0)
    
    rating = smoke.update_na_hms(camera)
    
    assert rating == constants.SMOKE_RATING_CLEAR


def test_update_na_hms_hms_kml_data_none(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    smoke.hms_kml_data = None
    camera = MockCamera(45.0, -95.0)
    
    mocker.patch.object(smoke, 'download_kml', return_value=None)
    
    with pytest.raises(NoSmokeData, match='No KML data'):
        smoke.update_na_hms(camera)


def test_update_na_hms_invalid_xml(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    smoke.hms_kml_data = b"not xml data"
    camera = MockCamera(45.0, -95.0)
    
    with pytest.raises(NoSmokeData, match='Unable to parse XML'):
        smoke.update_na_hms(camera)
    
    # Should force redownload by setting to None
    assert smoke.hms_kml_data is None


def test_update_na_hms_no_folders_found(mocker, flask_app):
    smoke = IndiAllskySmokeUpdate({})
    smoke.hms_kml_data = MOCK_KML_NO_FOLDERS.encode('utf-8')
    camera = MockCamera(45.0, -95.0)
    
    with pytest.raises(NoSmokeData, match='No folders in KML'):
        smoke.update_na_hms(camera)
