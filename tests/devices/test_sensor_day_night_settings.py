import logging
from types import SimpleNamespace

import pytest

from indi_allsky.devices.sensors import lightSensorSi1145, tempSensorSi7021


@pytest.mark.parametrize('day_level, night_level', [
    (2, 5), (-1, 5), (2, -1), (-1, -1), (0, 5), (2, 0),
])
def test_si7021_heater_uses_current_mode(monkeypatch, day_level, night_level):
    monkeypatch.setattr(tempSensorSi7021.time, 'sleep', lambda _: None)
    sensor = tempSensorSi7021.TempSensorSi7021({}, 'test', [], [])
    sensor.heater_level_day = day_level
    sensor.heater_level_night = night_level
    sensor.si7021 = SimpleNamespace(heater_enable=False, heater_level=None)

    for night in (False, True, False):
        previous_level = sensor.si7021.heater_level
        sensor.night = night
        sensor.update_sensor_settings()

        expected_level = night_level if night else day_level
        assert sensor.si7021.heater_enable is (expected_level >= 0)
        if expected_level >= 0:
            assert sensor.si7021.heater_level == expected_level
        else:
            assert sensor.si7021.heater_level == previous_level


@pytest.mark.parametrize('day_range_high', [False, True])
def test_si1145_log_matches_applied_ir_settings(monkeypatch, caplog, day_range_high):
    monkeypatch.setattr(lightSensorSi1145.time, 'sleep', lambda _: None)
    monkeypatch.setattr(lightSensorSi1145.logger, 'propagate', True)
    caplog.set_level(logging.INFO, logger='indi_allsky')
    sensor = lightSensorSi1145.LightSensorSi1145({}, 'test', [], [])
    sensor.vis_gain_day, sensor.vis_gain_night = 1, 2
    sensor.ir_gain_day, sensor.ir_gain_night = 3, 4
    sensor.vis_range_high_day, sensor.vis_range_high_night = True, False
    sensor.ir_range_high_day = day_range_high
    sensor.ir_range_high_night = not day_range_high
    sensor.si1145 = SimpleNamespace()

    for night in (False, True, False):
        sensor.astro_darkness = night
        sensor.update_sensor_settings()

        expected_gain = 4 if night else 3
        expected_range = not day_range_high if night else day_range_high
        assert sensor.si1145.ir_gain == expected_gain
        assert sensor.si1145.als_ir_range_high is expected_range
        assert sensor.si1145.vis_gain == (2 if night else 1)
        assert sensor.si1145.als_vis_range_high is (not night)
        assert caplog.messages[-1].endswith(
            'IR Gain: {0} - Range High: {1}'.format(expected_gain, expected_range)
        )
