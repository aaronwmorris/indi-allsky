import ast
import pathlib

from indi_allsky.focus.rigs import LIBCAMERA_SENSOR
from indi_allsky.focus.rigs import RIGS
from indi_allsky.focus.rigs import RigDecision
from indi_allsky.focus.rigs import decide

FORMS = pathlib.Path(__file__).resolve().parents[2] / 'indi_allsky' / 'flask' / 'forms.py'


def _interfaces():
    # Parse forms.py with ast; importing it would pull in Flask.
    tree = ast.parse(FORMS.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == 'CAMERA_INTERFACE_choices' for t in node.targets
        ):
            choices = ast.literal_eval(node.value)
            return [value for group in choices.values() for value, _label in group]
    raise AssertionError('CAMERA_INTERFACE_choices not found in forms.py')


def test_every_camera_interface_has_a_row():
    assert set(_interfaces()) <= set(RIGS)
    assert len(_interfaces()) == 28  # at 254379eb; a new camera type must fail this test until it gets a row


def test_rows_match_spec_6_9():
    assert decide('indi', 'ZWO CCD ASI676MC', True, True) == RigDecision('new', 'video', 'Live video · 10 fps')
    assert decide('indi', 'ZWO CCD ASI120MM', True, True) == RigDecision('new', 'stills', 'this camera model is not on the starlight list yet')
    assert decide('indi', 'ZWO CCD ASI676MC', False, True) == RigDecision('new', 'stills', "this camera's driver does not offer video")
    assert decide('libcamera_imx462', '', None, True) == RigDecision('new', 'stills', 'video for Pi cameras is not built yet')
    assert decide('libcamera_imx477', '', None, True) == RigDecision('new', 'stills', 'this sensor is not on the starlight list')
    assert decide('mqtt_imx477', '', None, True) == RigDecision('new', 'stills', 'live video is not available for this camera type')
    assert decide('indi_accumulator', '', None, True) == RigDecision('new', 'stills', 'live video is not available for this camera type')
    assert decide('indi_passive', '', None, True) == RigDecision('classic', None, 'Live focus and autofocus need a camera this program can command.')
    assert decide('pycurl_camera', '', None, True).page == 'classic'
    assert decide('test_rotating_stars', '', None, True) == RigDecision('new', 'video', 'Simulated camera')
    assert decide('test_bubbles', '', None, True) == RigDecision('new', 'video', 'Simulated camera')


def test_indi_driver_video_unknown_defers_picture_to_session_start():
    assert decide('indi', 'ZWO CCD ASI676MC', None, True) == RigDecision('new', None, '')


def test_libcamera_sensors_derive_from_the_value():
    assert LIBCAMERA_SENSOR['libcamera_imx462'] == 'IMX462'
    for ci in _interfaces():
        if ci.startswith('libcamera_'):
            assert ci in LIBCAMERA_SENSOR
            assert RIGS[ci] == 'libcamera'
    assert decide('libcamera_imx500_ai', '', None, True).reason == 'this sensor is not on the starlight list'
    assert decide('libcamera_64mp_hawkeye', '', None, True).reason == 'this sensor is not on the starlight list'
    assert decide('libcamera_imx296_gs_color', '', None, True).reason == 'this sensor is not on the starlight list'
    for ci in ('libcamera_imx327', 'libcamera_imx678', 'libcamera_imx335', 'libcamera_imx290'):
        assert decide(ci, '', None, True).reason == 'video for Pi cameras is not built yet'


def test_unreachable_capture_falls_back_for_every_rig():
    for ci in _interfaces():
        d = decide(ci, 'ZWO CCD ASI676MC', True, link_ok=False)
        assert d.page == 'classic'
        assert d.picture is None
        assert d.reason.startswith('The live focus page cannot reach the capture program.')
