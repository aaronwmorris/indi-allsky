from indi_allsky.focus.starlight import CAMERA_MODELS
from indi_allsky.focus.starlight import SENSORS
from indi_allsky.focus.starlight import sensor_for_device
from indi_allsky.focus.starlight import video_allowed


def test_every_entry_has_a_source():
    for s in SENSORS.values():
        assert s.source.startswith('sony-semicon.com/') or s.source.startswith('http')
    for m in CAMERA_MODELS:
        assert m.source


def test_asi676mc_maps_to_imx676_and_is_allowed():
    assert sensor_for_device('ZWO CCD ASI676MC') == 'IMX676'
    assert video_allowed('IMX676') is True


def test_unlisted_camera_gets_no_video():
    assert sensor_for_device('ZWO CCD ASI120MM') is None
    assert video_allowed(None) is False
    assert video_allowed('IMX477') is False


def test_seven_sensors_from_spec():
    assert set(SENSORS) == {'IMX676', 'IMX462', 'IMX290', 'IMX327', 'IMX335', 'IMX678', 'IMX585'}


def test_device_match_is_case_insensitive():
    assert sensor_for_device('zwo ccd asi676mc') == 'IMX676'


def test_read_by_values_are_known():
    for s in SENSORS.values():
        assert s.read_by in ('me', 'builder', 'agent')
    for m in CAMERA_MODELS:
        assert m.read_by in ('me', 'builder', 'agent')


def test_every_model_points_at_a_listed_sensor():
    for m in CAMERA_MODELS:
        assert m.sensor in SENSORS
