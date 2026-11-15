import pytest

from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky.devices.sensors import lightSensorTsl2591 as driver


class Light:
    """Simulate ADC counts per 1x / 100 ms and the legacy packed channel API."""

    gain = 0
    integration_time = 0
    rates = (0.0, 0.0)
    packed = True

    def __init__(self):
        self.reads = []

    @property
    def exposure(self):
        return (1, 25, 428, 9876)[self.gain // 16] * (self.integration_time + 1)

    @property
    def raw_luminosity(self):
        limit = 36863 if self.integration_time == 0 else 65535
        return tuple(min(limit, round(rate * self.exposure)) for rate in self.rates)

    @property
    def lux(self):
        self.reads.append((self.gain, self.integration_time))
        ch0, ch1 = self.raw_luminosity
        limit = 36863 if self.integration_time == 0 else 65535
        if max(ch0, ch1) >= limit:
            raise RuntimeError('Overflow reading light channels!')
        return 4.08 / self.exposure * max(ch0 - 1.64 * ch1, 0.59 * ch0 - 0.86 * ch1)

    @property
    def visible(self):
        return self.full_spectrum - self.raw_luminosity[1]

    @property
    def full_spectrum(self):
        ch0, ch1 = self.raw_luminosity
        return (ch1 << 16) | ch0 if self.packed else ch0


@pytest.fixture
def sensor(monkeypatch):
    monkeypatch.setattr(driver.time, 'sleep', lambda _: None)
    sensor = driver.LightSensorTsl2591({}, 'test', [], [15])
    sensor.gain_levels = (0, 16, 32, 48)
    sensor.gain_night, sensor.integration_night = 48, 5
    sensor.gain_day, sensor.integration_day = 0, 0
    sensor.disable_day = False
    sensor.tsl2591 = Light()
    return sensor


@pytest.mark.parametrize('packed', [True, False])
def test_dusk_recovers_underflow_in_same_poll_and_dawn_keeps_sensitivity(sensor, packed):
    light = sensor.tsl2591
    light.packed = packed
    # CH0=20 and CH1=6 at 9876x / 600 ms, both zero at 1x / 100 ms.
    light.rates = (20 / 59256, 6 / 59256)
    sensor.astro_av[0] = -12
    sample = sensor.update()['data']
    full = (6 << 16) | 20 if packed else 20
    assert sample == (pytest.approx(0.00069955, rel=0.001), full - 6, 6, full, 0, 0)
    assert light.reads == [(0, 0), (48, 5)]

    sensor.astro_av[0] = -18
    assert sensor.update()['data'][4] > 0
    sensor.astro_av[0] = -17.99
    assert sensor.update()['data'] == sample
    assert light.reads[2:] == [(48, 5), (48, 5)]


def test_dawn_saturation_reduces_range_and_recovers_as_sky_darkens(sensor, monkeypatch):
    sleeps = []
    monkeypatch.setattr(driver.time, 'sleep', sleeps.append)
    light = sensor.tsl2591
    light.gain, light.integration_time = 48, 5
    light.rates = (14000, 1000)
    sensor.astro_av[0] = -5
    sample = sensor.update()['data']
    assert light.reads == [(48, 5), (32, 5), (16, 5), (0, 5), (0, 0)]
    assert sleeps[-1] == pytest.approx(0.7)  # 600 ms in flight + 100 ms new
    assert sample[0] == pytest.approx(4.08 * (14000 - 1640))
    light.reads.clear()
    assert sensor.update()['data'] == sample
    assert light.reads == [(0, 0)]

    light.rates = (0.01, 0.002)
    assert sensor.update()['data'][0] > 0
    assert light.reads[-1] == (48, 5)


def test_day_profile_and_user_disabled_daytime(sensor):
    light = sensor.tsl2591
    light.gain, light.integration_time = 48, 5
    light.rates = (250, 50)
    assert sensor.update()['data'][0] > 0
    assert light.reads == [(0, 0)]
    sensor.disable_day = True
    sensor.astro_av[0] = -17
    assert sensor.update()['sample_disabled']
    assert light.reads == [(0, 0)]


def test_true_darkness_does_not_fabricate_lux_or_sqm(sensor):
    sensor.astro_av[0] = -20
    assert sensor.update()['data'] == (0, 0, 0, 0, 0, 0)
    assert (sensor.tsl2591.gain, sensor.tsl2591.integration_time) == (48, 5)


def test_ir_saturation_and_upward_headroom_use_both_raw_channels(sensor):
    sensor.astro_av[0] = -12
    light = sensor.tsl2591
    light.rates = (1, 18000)
    light.gain, light.integration_time = 32, 5
    sample = sensor.update()['data']
    assert sample[0] is None  # negative lux estimate under infrared light
    assert sample[2] == 18000
    assert light.reads[-1] == (0, 0)
    light.reads.clear()
    sensor.update()
    assert light.reads == [(0, 0)]


def test_saturation_at_minimum_is_not_reported_as_zero(sensor):
    sensor.tsl2591.rates = (50000, 1000)
    with pytest.raises(SensorReadException, match='saturated'):
        sensor.update()
    assert sensor.tsl2591.reads == [(0, 0)]


def test_non_overflow_sensor_errors_are_not_retried(sensor):
    class BadLight(Light):
        @property
        def lux(self):
            raise RuntimeError('I2C read failed')

    sensor.tsl2591 = BadLight()
    with pytest.raises(SensorReadException, match='I2C'):
        sensor.update()
    assert sensor.tsl2591.gain == 0
