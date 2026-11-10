import ast
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indi_allsky import constants
from indi_allsky.exceptions import BinModeException, CameraException, TimeOutException


@pytest.fixture
def camera(tmp_path):
    # Run the production subprocess driver without loading hardware-only PyIndi.
    source = Path(__file__).resolve().parents[2] / 'indi_allsky/camera/libcamera.py'
    definition = next(n for n in ast.parse(source.read_text()).body
                      if isinstance(n, ast.ClassDef) and n.name == 'IndiClientLibCameraGeneric')
    scope = dict(IndiClient=object, constants=constants, Path=Path, subprocess=subprocess,
                 time=time, tempfile=tempfile, BinModeException=BinModeException,
                 CameraException=CameraException, TimeOutException=TimeOutException,
                 logger=logging.getLogger('indi_allsky'))
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), scope)
    driver = object.__new__(scope[definition.name])
    program = tmp_path / 'rpicam-still'
    program.write_text(f'#!{sys.executable}\n' + """
import os, sys, time
from pathlib import Path
mode = os.environ['CAMERA_TEST_MODE']
if mode == 'sleep':
    time.sleep(30)
if mode == 'noisy':
    sys.stdout.buffer.write(b'x' * (1024 * 1024))
    Path(sys.argv[sys.argv.index('--output') + 1]).write_bytes(b'raw')
if mode == 'empty':
    Path(sys.argv[sys.argv.index('--output') + 1]).touch()
sys.exit(3 if mode == 'error' else 0)
""")
    program.chmod(0o755)
    driver.ccd_device = SimpleNamespace(driver_exec=str(program))
    driver.config, driver.night_av = {}, [True]
    driver.gain, driver.binning = 1, 1
    driver._expUtils = SimpleNamespace(GAIN_CURRENT=1)
    driver._getBinModeOptions = lambda _: ''
    driver._processMetadata, driver._queueImage = Mock(), Mock()
    driver.active_exposure, driver.libcamera_process = False, None
    yield driver
    driver.closeCameraProcess()
    driver._removeCaptureFiles()


@pytest.mark.parametrize(('mode', 'status'), [('noisy', 'READY'), ('error', 'ERROR'),
                                               ('missing', 'ERROR'), ('empty', 'ERROR')])
def test_failed_or_noisy_external_capture(camera, mode, status, monkeypatch):
    monkeypatch.setenv('CAMERA_TEST_MODE', mode)
    camera.setCcdExposure(1.0, 1, 1)
    camera.libcamera_process.wait(timeout=5)
    assert camera.getCcdExposureStatus() == (True, status)
    if status == 'READY':
        camera._queueImage.assert_called_once()
    else:
        camera._queueImage.assert_not_called()
        assert not camera.current_exposure_file_p.exists()


def test_sync_timeout_reaps_child_before_next_request(camera, monkeypatch):
    monkeypatch.setenv('CAMERA_TEST_MODE', 'sleep')
    with pytest.raises(TimeOutException):
        camera.setCcdExposure(1.0, 1, 1, sync=True, timeout=.1)
    assert camera.libcamera_process.poll() is not None
    assert not camera.active_exposure
    camera._queueImage.assert_not_called()


def test_failed_kill_keeps_owner_and_rejects_overlapping_request(camera):
    child = Mock(pid=1234)
    child.poll.return_value = None
    child.wait.side_effect = subprocess.TimeoutExpired('rpicam', 3)
    camera.libcamera_process = child
    camera.active_exposure = True
    camera.current_exposure_file_p = camera.current_metadata_file_p = None
    assert not camera.abortCcdExposure()
    camera.setCcdExposure(2.0, 1, 1)
    assert camera.libcamera_process is child
    assert camera.getCcdExposureStatus() == (False, 'BUSY')
    child.poll.return_value = -9  # finally reaped
