from multiprocessing import Queue, Value, Array
from unittest.mock import MagicMock
import pytest

from indi_allsky.camera.fake_indi import FakeIndiClient, FakeIndiCcd
import indi_allsky.camera as camera_pkg


def test_camera_package_exports():
    assert hasattr(camera_pkg, 'test_bubbles')
    assert hasattr(camera_pkg, 'test_rotating_stars')
    assert hasattr(camera_pkg, 'libcamera_imx477')


def test_fake_indi_client_properties():
    image_q = Queue()
    lat_v = Value('d', 0.0)
    long_v = Value('d', 0.0)
    ra_v = Value('d', 0.0)
    dec_v = Value('d', 0.0)
    gain_av = Array('i', [0]*10)
    bin_av = Array('i', [1]*10)
    night_av = Array('i', [1, 0])

    client = FakeIndiClient(
        {},
        image_q,
        lat_v,
        long_v,
        ra_v,
        dec_v,
        gain_av,
        bin_av,
        night_av,
    )

    client.exposure = 5.5
    assert client.exposure == 5.5

    client.gain = 100
    assert client.gain == 100

    client.timeout = 30.0
    assert client.timeout == 30.0

    client.ccd_device = "CCD_SIM"
    assert client.ccd_device == "CCD_SIM"

    client.telescope_device = "SCOPE_SIM"
    assert client.telescope_device == "SCOPE_SIM"

    client.gps_device = "GPS_SIM"
    assert client.gps_device == "GPS_SIM"

    client.filename_t = "test_{0:d}.fits"
    assert client.filename_t == "test_{0:d}.fits"


def test_fake_indi_ccd_properties():
    ccd = FakeIndiCcd()
    ccd.device_name = "CCD_SIM"
    assert ccd.getDeviceName() == "CCD_SIM"
