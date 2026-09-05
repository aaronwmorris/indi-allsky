from multiprocessing import Array, Queue
import pytest
from unittest.mock import MagicMock, patch

from indi_allsky.sensor import SensorWorker
from indi_allsky import constants


@pytest.fixture
def sensor_worker_setup():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_simulator',
            'A_LABEL': 'Sim',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        },
        'DEW_HEATER': {
            'CLASSNAME': 'dew_heater_simulator',
            'THOLD_ENABLE': True,
            'LEVEL_DEF': 25,
            'HOLD_SECONDS': 0,
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
            'DEWPOINT_USER_VAR_SLOT': 'sensor_user_2',
            'THOLD_DIFF_LOW': 15,
            'THOLD_DIFF_MED': 10,
            'THOLD_DIFF_HIGH': 5,
        },
        'FAN': {
            'CLASSNAME': 'fan_simulator',
            'THOLD_ENABLE': True,
            'ENABLE_NIGHT': True,
            'LEVEL_DEF': 30,
            'HOLD_SECONDS': 0,
            'TARGET': 25.0,
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        },
        'GPIO': {
            'CLASSNAME': 'gpio_simulator',
        },
    }

    sensor_q = Queue()
    error_q = Queue()
    sensors_temp_av = Array('f', [0.0] * 110)
    sensors_user_av = Array('f', [0.0] * 110)
    night_av = Array('i', [1, 0])
    astro_av = Array('f', [0.0] * 10)

    worker = SensorWorker(
        0,
        config,
        sensor_q,
        error_q,
        sensors_temp_av,
        sensors_user_av,
        night_av,
        astro_av,
    )
    return worker


def test_sensor_worker_initialization_and_control(sensor_worker_setup):
    worker = sensor_worker_setup

    worker.init_sensors()
    worker.init_gpio()
    worker.init_dew_heater()
    worker.init_fan()

    assert worker.dew_heater is not None
    assert worker.fan is not None
    assert worker.gpio is not None

    # Test day/night transition
    worker.night = True
    worker.night_day_change()
    assert worker.gpio.state == 0

    worker.night = False
    worker.night_day_change()
    assert worker.gpio.state == 0

    # Test dew heater thresholds (active at night)
    worker.night = True
    worker.sensors_user_av[10] = 12.0  # temp
    worker.sensors_user_av[2] = 10.0   # dew point (diff = 2.0 <= THOLD_DIFF_HIGH)
    with patch.object(worker, 'set_dew_heater') as mock_set_dh:
        worker.check_dew_heater_thresholds()
        mock_set_dh.assert_called_with(worker.dh_level_high)

    # Test fan thresholds
    worker.sensors_user_av[10] = 35.0  # temp > target (25.0)
    with patch.object(worker, 'set_fan') as mock_set_fan:
        worker.check_fan_thresholds()
        mock_set_fan.assert_called_with(100)

    # Test signal handlers
    worker.sigterm_handler_worker(15, None)
    assert worker._shutdown is True

    worker.sighup_handler_worker(1, None)
    assert worker._shutdown is True

    worker.sigint_handler_worker(2, None)
    assert worker._shutdown is True
