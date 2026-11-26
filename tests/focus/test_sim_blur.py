"""The simulated star camera blurs its stars by the simulated focuser's lens position."""

from __future__ import annotations

import sys
import time
import types

import cv2
import numpy as np
import pytest

from indi_allsky.focus import measure

FOCUSER_MODULE = 'indi_allsky.devices.focusers.focuserSimulator'
WIDTH, HEIGHT = 240, 160
NOISE = 1.0

# The camera draws on a 3x canvas and crops it starting at these canvas coordinates.
CROP_X0 = int(WIDTH * 3 / 2 - WIDTH / 2)
CROP_Y0 = int(HEIGHT * 3 / 2 - HEIGHT * 0.7)
STAR_COLOUR = 20000.0
SPOTS = [(50, 40), (120, 40), (190, 40), (50, 110), (120, 110), (190, 110)]  # in the cropped frame


@pytest.fixture
def make_camera(fake_pyindi):
    tc = fake_pyindi('test_cameras')

    def make(radius=1):
        cam = tc.IndiClientTestCameraRotatingStars.__new__(tc.IndiClientTestCameraRotatingStars)
        cam.camera_info = {'width': WIDTH, 'height': HEIGHT}
        cam.rotation_factor = 0.0
        cam._last_exposure_time = time.time()
        cam._stars_store_p = None
        cam._image_circle_diameter = 0  # no image circle mask
        cam._image_circle_alpha_mask_dict = {}
        cam.stars_array = np.array(
            [[CROP_X0 + x, CROP_Y0 + y, radius, STAR_COLOUR, STAR_COLOUR, STAR_COLOUR] for x, y in SPOTS],
            dtype=np.float32,
        ).T.copy()
        return cam

    return make


def set_lens(monkeypatch, position):
    module = types.ModuleType(FOCUSER_MODULE)
    module.SIMULATED_LENS = None if position is None else types.SimpleNamespace(lens_position=position)
    monkeypatch.setitem(sys.modules, FOCUSER_MODULE, module)


def render(cam):
    cam.updateImage(1)
    return cam._image


def sizes(frame):
    gray = frame.astype(np.float32).mean(axis=2)
    out = []
    for x, y in SPOTS:
        reading = measure.measure_star(gray, x, y, NOISE)
        assert reading is not None
        out.append(reading.size)
    return float(np.mean(out))


def flux(frame, x, y, half=20):
    bg = frame[0, 0, 0]
    return float((frame[y - half:y + half + 1, x - half:x + half + 1, 0].astype(np.float64) - bg).sum())


def test_smallest_at_best_focus_and_grows_either_side(make_camera, monkeypatch):
    cam = make_camera()
    best = cam.SIM_FOCUS_BEST_STEPS
    assert best != 0  # autofocus has to find it

    at = {}
    for offset in (-100, -50, -25, 0, 25, 50, 100):
        set_lens(monkeypatch, best + offset)
        at[offset] = sizes(render(cam))

    assert at[0] == min(at.values())
    assert at[0] < at[25] < at[50] < at[100]
    assert at[0] < at[-25] < at[-50] < at[-100]
    assert at[100] > 2.5 * at[0]


def test_blur_reaches_a_plateau(make_camera, monkeypatch):
    cam = make_camera()
    best = cam.SIM_FOCUS_BEST_STEPS
    set_lens(monkeypatch, best + 150)
    far = sizes(render(cam))
    set_lens(monkeypatch, best + 300)
    farther = sizes(render(cam))
    assert farther == pytest.approx(far, rel=0.05)


def test_flux_is_conserved_while_the_peak_drops(make_camera, monkeypatch):
    cam = make_camera(radius=2)
    best = cam.SIM_FOCUS_BEST_STEPS
    set_lens(monkeypatch, best)
    sharp = render(cam)
    set_lens(monkeypatch, best + 90)
    soft = render(cam)

    x, y = SPOTS[1]
    assert flux(soft, x, y) == pytest.approx(flux(sharp, x, y), rel=0.10)
    assert soft[y, x, 0] < 0.5 * sharp[y, x, 0]


def test_without_a_lens_it_renders_circles_as_before(make_camera, monkeypatch):
    cam = make_camera(radius=2)

    expected = np.full([HEIGHT * 3, WIDTH * 3, 3], cam.background_color, dtype=np.uint16)
    for i in range(cam.stars_array.shape[1]):
        cv2.circle(
            expected,
            center=(round(cam.stars_array[0][i]), round(cam.stars_array[1][i])),
            radius=int(cam.stars_array[2][i]),
            color=(int(cam.stars_array[3][i]), int(cam.stars_array[4][i]), int(cam.stars_array[5][i])),
            thickness=cv2.FILLED,
            lineType=cv2.LINE_AA,
        )
    expected = expected[CROP_Y0:CROP_Y0 + HEIGHT, CROP_X0:CROP_X0 + WIDTH]

    monkeypatch.delitem(sys.modules, FOCUSER_MODULE, raising=False)
    assert np.array_equal(render(cam), expected)

    set_lens(monkeypatch, None)  # the module is there, but no simulator was constructed
    assert np.array_equal(render(cam), expected)


def test_lens_is_read_on_every_frame(make_camera, monkeypatch):
    cam = make_camera()
    best = cam.SIM_FOCUS_BEST_STEPS
    set_lens(monkeypatch, best)
    sharp = sizes(render(cam))
    set_lens(monkeypatch, best + 60)
    assert sizes(render(cam)) > sharp
