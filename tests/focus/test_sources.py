from __future__ import annotations

import queue
import sys
import threading
import time
import types

import cv2
import numpy as np
import pytest
from astropy.io import fits

from indi_allsky.focus.sources import RawFrame
from indi_allsky.focus.sources import StillsSource
from indi_allsky.focus.sources import load_still


def wait_for(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while True:
        value = cond()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(0.01)


class FakeCamera(object):
    """The parts of a camera client StillsSource uses."""

    def __init__(self):
        self.image_q = queue.Queue()
        self.exposures = []
        self.aborts = 0
        self.status_polls = 0
        self._lock = threading.Lock()

    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        with self._lock:
            self.exposures.append((exposure, gain, binning, sync))

    def abortCcdExposure(self):
        self.aborts += 1

    def getCcdExposureStatus(self):
        self.status_polls += 1
        return True, 'READY'

    def swap(self, new_q):
        old, self.image_q = self.image_q, new_q
        return old


@pytest.fixture
def camera():
    return FakeCamera()


@pytest.fixture
def source(camera):
    src = StillsSource(camera, camera.swap)
    yield src
    src.stop()


def mosaic(h=32, w=48, seed=3):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 60000, size=(h, w), dtype=np.uint16)


def write_fits(path, data, bayer='RGGB'):
    hdu = fits.PrimaryHDU(data)
    if bayer is not None:
        hdu.header['BAYERPAT'] = bayer
    hdu.writeto(str(path))
    return str(path)


def job(path, exposure=1.0, gain=100.0, t=1234.5):
    return {'filename': str(path), 'exposure': exposure, 'gain': gain, 'exp_time': t}


# --- loading ----------------------------------------------------------------------------------------------------

def test_load_fits_keeps_mosaic_and_bayer(tmp_path):
    data = mosaic()
    raw, full_scale, bayer = load_still(write_fits(tmp_path / 'a.fit', data))
    np.testing.assert_array_equal(raw, data)
    assert full_scale == 65535.0
    assert bayer == 'RGGB'


def test_load_fits_empty_bayer_is_mono(tmp_path):
    # constants.CFA_STR_MAP treats '' as mono (the sv305 edge case).
    _, _, bayer = load_still(write_fits(tmp_path / 'a.fits', mosaic(), bayer=''))
    assert bayer is None
    _, _, bayer = load_still(write_fits(tmp_path / 'b.fits', mosaic(), bayer=None))
    assert bayer is None


def test_load_8bit_fits_full_scale(tmp_path):
    data = (mosaic() // 257).astype(np.uint8)
    raw, full_scale, _ = load_still(write_fits(tmp_path / 'a.fit', data))
    np.testing.assert_array_equal(raw, data)
    assert full_scale == 255.0


def test_load_jpg_is_gray_8bit(tmp_path):
    bgr = np.zeros((20, 30, 3), np.uint8)
    bgr[:, :, 1] = 200
    path = tmp_path / 'a.jpg'
    cv2.imwrite(str(path), bgr)
    raw, full_scale, bayer = load_still(str(path))
    assert raw.shape == (20, 30)
    assert full_scale == 255.0
    assert bayer is None
    assert abs(float(raw.mean()) - 0.587 * 200) < 3


def test_load_png_16bit(tmp_path):
    data = mosaic()
    path = tmp_path / 'a.png'
    cv2.imwrite(str(path), data)
    raw, full_scale, bayer = load_still(str(path))
    np.testing.assert_array_equal(raw, data)
    assert full_scale == 65535.0
    assert bayer is None


def test_load_dng_uses_rawpy(tmp_path, monkeypatch):
    # rawpy cannot write a DNG, so a stand-in module checks the dng branch (the import there is lazy).
    data = mosaic()

    class FakeRaw(object):
        raw_image = data
        raw_pattern = np.array([[0, 1], [3, 2]])
        color_desc = b'RGBG'
        white_level = 4095

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            pass

    fake = types.ModuleType('rawpy')
    fake.imread = lambda path: FakeRaw()
    monkeypatch.setitem(sys.modules, 'rawpy', fake)
    path = tmp_path / 'a.dng'
    path.write_bytes(b'not really a dng')
    raw, full_scale, bayer = load_still(str(path))
    np.testing.assert_array_equal(raw, data)
    assert full_scale == 4095.0
    assert bayer == 'RGGB'


def test_load_unknown_suffix_raises(tmp_path):
    path = tmp_path / 'a.tif'
    path.write_bytes(b'x')
    with pytest.raises(ValueError):
        load_still(str(path))


# --- the source ---------------------------------------------------------------------------------------------------

def test_start_swaps_queue_and_exposes(camera, source):
    original = camera.image_q
    source.start(None, 1.0, 100.0)
    assert camera.image_q is not original
    assert camera.exposures == [(1.0, 100.0, 1, False)]


def test_put_queues_frame_deletes_file_and_exposes_again(tmp_path, camera, source):
    data = mosaic()
    path = write_fits(tmp_path / 'a.fit', data)
    source.start(None, 1.0, 100.0)
    camera.image_q.put(job(path, t=1234.5))

    frame = source.frames.get(timeout=2.0)
    assert isinstance(frame, RawFrame)
    np.testing.assert_array_equal(frame.raw, data)
    assert (frame.full_scale, frame.bayer, frame.t_end, frame.exposure, frame.gain) == (
        65535.0, 'RGGB', 1234.5, 1.0, 100.0)
    assert wait_for(lambda: len(camera.exposures) == 2)
    assert not (tmp_path / 'a.fit').exists()


def test_roi_crops_on_the_bayer_grid(tmp_path, camera, source):
    data = mosaic()
    source.start((3, 5, 10, 7), 1.0, 100.0)
    camera.image_q.put(job(write_fits(tmp_path / 'a.fit', data)))
    frame = source.frames.get(timeout=2.0)
    # x and y round down to even so the crop keeps the Bayer pattern; sizes round down to even.
    np.testing.assert_array_equal(frame.raw, data[4:10, 2:12])
    np.testing.assert_array_equal(source.whole_frame(), data)


def test_set_camera_applies_to_next_exposure(tmp_path, camera, source):
    source.start(None, 1.0, 100.0)
    source.set_camera(2.0, 50.0)
    camera.image_q.put(job(write_fits(tmp_path / 'a.fit', mosaic())))
    source.frames.get(timeout=2.0)
    assert wait_for(lambda: len(camera.exposures) == 2)
    assert camera.exposures[-1] == (2.0, 50.0, 1, False)


def test_bad_file_is_deleted_and_capture_goes_on(tmp_path, camera, source, caplog):
    path = tmp_path / 'bad.fit'
    path.write_bytes(b'not a fits file')
    source.start(None, 1.0, 100.0)
    camera.image_q.put(job(path))
    assert wait_for(lambda: len(camera.exposures) == 2)
    assert not path.exists()
    assert source.frames.empty()


def test_stop_restores_queue_and_late_put_is_discarded(tmp_path, camera, source):
    original = camera.image_q
    source.start(None, 1.0, 100.0)
    adapter = camera.image_q
    source.stop()
    assert camera.image_q is original
    assert camera.aborts == 1

    path = write_fits(tmp_path / 'late.fit', mosaic())
    adapter.put(job(path))
    assert not (tmp_path / 'late.fit').exists()
    assert original.empty()
    assert source.frames.empty()
    assert camera.exposures == [(1.0, 100.0, 1, False)]
    source.stop()  # idempotent
    assert camera.image_q is original


def test_polls_camera_status_while_waiting(camera, source):
    # libcamera queues its picture from getCcdExposureStatus, which the capture loop no longer calls.
    source.start(None, 1.0, 100.0)
    assert wait_for(lambda: camera.status_polls >= 2)


def test_whole_frame_times_out_without_a_picture(camera, source):
    source.start(None, 1.0, 100.0)
    with pytest.raises(TimeoutError):
        source.whole_frame(timeout=0.05)


def test_whole_frame_ends_when_the_source_stops(camera, source):
    source.start(None, 1.0, 100.0)
    errors = []

    def wait():
        try:
            source.whole_frame(timeout=10.0)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=wait)
    t.start()
    time.sleep(0.1)
    source.stop()
    t.join(2.0)
    assert not t.is_alive()
    assert [type(e) for e in errors] == [RuntimeError]


class LateCamera(FakeCamera):
    """An exposure starts when setCcdExposure returns, and lands on whatever image_q the camera holds then
    unless an abort came after it."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.pending = False
        self.events = []

    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        if self.exposures:  # the first comes from start(); hold the ones the stills thread starts
            self.entered.set()
            self.gate.wait(5.0)
        super().setCcdExposure(exposure, gain, binning, sync)
        self.pending = True
        self.events.append('expose')

    def abortCcdExposure(self):
        super().abortCcdExposure()
        self.pending = False
        self.events.append('abort')

    def finish(self, path):
        if self.pending:
            self.pending = False
            self.image_q.put(job(path))


def test_stop_waits_for_an_exposure_being_started(tmp_path):
    camera = LateCamera()
    original = camera.image_q
    src = StillsSource(camera, camera.swap)
    src.start(None, 1.0, 100.0)
    camera.image_q.put(job(write_fits(tmp_path / 'a.fit', mosaic())))
    src.frames.get(timeout=2.0)
    assert camera.entered.wait(2.0)  # past the running check, about to start an exposure
    threading.Timer(0.2, camera.gate.set).start()  # it starts once stop() is under way
    src.stop()
    assert camera.events[-1] == 'abort'  # no exposure started after the abort
    n = len(camera.exposures)
    camera.finish(write_fits(tmp_path / 'late.fit', mosaic()))
    time.sleep(0.1)
    assert len(camera.exposures) == n
    assert original.empty()


def test_colour_fits_is_not_a_mosaic(tmp_path):
    planes = np.stack([mosaic(seed=s) for s in (1, 2, 3)])
    raw, _, bayer = load_still(write_fits(tmp_path / 'c.fit', planes))
    assert raw.ndim == 2
    assert bayer is None


def test_source_knows_the_bayer_of_its_last_picture(tmp_path, camera, source):
    assert source.bayer is None
    source.start(None, 1.0, 100.0)
    camera.image_q.put(job(write_fits(tmp_path / 'a.fit', mosaic())))
    source.frames.get(timeout=2.0)
    assert source.bayer == 'RGGB'
