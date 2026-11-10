from types import SimpleNamespace

import pytest

from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky.devices.sensors import lightSensorTsl2591 as driver


class Light:
    integration_time = 5
    gain = 48
    visible = 18000
    infrared = 1000
    full_spectrum = (1000 << 16) | 19000

    @property
    def lux(self):
        if self.gain >= 32:
            raise RuntimeError('Overflow reading light channels!')
        return 1.25


def test_saturation_restores_working_sample_and_recovers_sensitivity(monkeypatch):
    sleeps = []
    monkeypatch.setattr(driver.time, 'sleep', sleeps.append)
    sensor = driver.LightSensorTsl2591({}, 'test', [], [])
    sensor.gain_levels = (0, 16, 32, 48)
    sensor.gain_night = 48
    sensor.astro_darkness = True
    sensor.tsl2591 = Light()
    assert sensor.read_channels() == (1.25, 18000, 1000, (1000 << 16) | 19000)
    assert sensor.tsl2591.gain == 16
    assert len(sleeps) == 2
    sensor.tsl2591.full_spectrum = 150
    sensor.tsl2591.infrared = 5
    assert sensor.read_channels()[0] == 1.25
    assert sensor.tsl2591.gain == 32
    assert sensor.gain_night == 48


def test_non_overflow_sensor_errors_are_not_retried(monkeypatch):
    class BadLight(Light):
        @property
        def lux(self):
            raise RuntimeError('I2C read failed')

    sensor = SimpleNamespace(tsl2591=BadLight(), astro_darkness=True, gain_night=48,
                             gain_levels=(0, 16, 32, 48))
    with pytest.raises(SensorReadException, match='I2C'):
        driver.LightSensorTsl2591.read_channels(sensor)
    assert sensor.tsl2591.gain == 48
