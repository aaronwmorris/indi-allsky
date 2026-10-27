import math
import logging
from types import SimpleNamespace
from multiprocessing import Array

import pytest

from indi_allsky.devices.sensors.lightSensorTsl2561 import LightSensorTsl2561
from indi_allsky.devices.sensors.lightSensorTsl2591 import LightSensorTsl2591
from indi_allsky.devices.exceptions import SensorReadException


def test_tsl2561_clipping_none_lux_logged_once(caplog):
    caplog.set_level(logging.WARNING, logger='indi_allsky')
    astro_av = [0.0]  # Day (alt > -18.0)
    sensor = LightSensorTsl2561({}, 'test_tsl2561', [0], astro_av)
    sensor.disable_day = False
    sensor.update_sensor_settings = lambda: None

    # Simulate clipped sensor: lux is None, raw channels saturated
    sensor.tsl2561 = SimpleNamespace(lux=None, broadband=4876, infrared=210)

    # First cycle: should handle None without exception and log warning once
    data = sensor.update()
    assert math.isnan(data['data'][0]), f"Expected NaN lux, got {data['data'][0]}"
    assert data['data'][1] == 4876, "Broadband count should be preserved"
    assert data['data'][2] == 210, "Infrared count should be preserved"
    assert any('clipped or out of range' in msg for msg in caplog.messages)

    # Second cycle while still clipped: should NOT duplicate warning
    caplog.clear()
    data2 = sensor.update()
    assert math.isnan(data2['data'][0])
    assert not any('clipped or out of range' in msg for msg in caplog.messages), "Warning should not be repeated"

    # Recovery cycle: valid lux reading
    caplog.set_level(logging.INFO, logger='indi_allsky')
    sensor.tsl2561.lux = 1250.5
    data3 = sensor.update()
    assert data3['data'][0] == 1250.5
    assert sensor._clipped is False
    assert any('returned to valid range' in msg for msg in caplog.messages)


def test_tsl2591_clipping_overflow_logged_once(caplog):
    caplog.set_level(logging.WARNING, logger='indi_allsky')
    astro_av = [0.0]
    sensor = LightSensorTsl2591({}, 'test_tsl2591', [0], astro_av)
    sensor.disable_day = False
    sensor.update_sensor_settings = lambda: None

    # Mock hardware raising RuntimeError Overflow (Adafruit saturation signal)
    class MockOverflowTsl2591:
        @property
        def lux(self):
            raise RuntimeError("Overflow reading light channels")
        @property
        def infrared(self):
            return 50000
        @property
        def visible(self):
            return 65535
        @property
        def full_spectrum(self):
            return 65535

    sensor.tsl2591 = MockOverflowTsl2591()

    # First cycle: overflow should be treated as clipped without raising SensorReadException
    data = sensor.update()
    assert math.isnan(data['data'][0])
    assert data['data'][1] == 65535  # visible
    assert data['data'][2] == 50000  # infrared
    assert any('clipped or out of range' in msg for msg in caplog.messages)

    # Second cycle: warning should not be duplicated
    caplog.clear()
    data2 = sensor.update()
    assert math.isnan(data2['data'][0])
    assert not any('clipped or out of range' in msg for msg in caplog.messages)

    # Recovery cycle
    caplog.set_level(logging.INFO, logger='indi_allsky')
    sensor.tsl2591 = SimpleNamespace(lux=350.25, infrared=1200, visible=4500, full_spectrum=5700)
    data3 = sensor.update()
    assert data3['data'][0] == 350.25
    assert sensor._clipped is False
    assert any('returned to valid range' in msg for msg in caplog.messages)


def test_sensor_slots_cleared_on_exception():
    from indi_allsky.sensor import SensorWorker

    sensors_user_av = Array('f', [123.4 for _ in range(110)])
    mock_sensor = SimpleNamespace(
        slot=10,
        METADATA={'count': 5},
        update=lambda: (_ for _ in ()).throw(SensorReadException("I2C read failure")),
    )

    # Instantiate minimal sensor manager
    mgr = SimpleNamespace(
        sensors=[mock_sensor],
        sensors_user_av=sensors_user_av,
    )

    # Call update_sensors logic directly
    SensorWorker.update_sensors(mgr)

    # Verify that slots 10 through 14 are cleared to NaN instead of retaining stale 123.4
    for i in range(10, 15):
        assert math.isnan(sensors_user_av[i]), f"Slot {i} should be NaN, got {sensors_user_av[i]}"

