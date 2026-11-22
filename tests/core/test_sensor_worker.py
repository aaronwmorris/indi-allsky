import time
from multiprocessing import Array, Queue
import pytest
from unittest.mock import MagicMock, patch, PropertyMock


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


def test_sensor_worker_lifecycle_and_run(sensor_worker_setup):
    worker = sensor_worker_setup
    from indi_allsky.devices.exceptions import DeviceControlException

    # 1. run() uncaught exception
    with patch.object(worker, 'saferun', side_effect=RuntimeError("Worker error")):
        with pytest.raises(RuntimeError):
            worker.run()
        err, tb = worker.error_q.get(timeout=2)
        assert "Worker error" in err

    # 2. saferun loop with sleep, unknown command, and normal execution
    loop_count = [0]
    def mock_sleep(s):
        loop_count[0] += 1
        if loop_count[0] == 1:
            worker.sensor_q.put({'unknown': 'cmd'})
        elif loop_count[0] == 2:
            # Trigger night/day change and log statements
            worker.night_av[constants.NIGHT_NIGHT] = 0
            worker.sensors_user_av[constants.SENSOR_USER_DEW_POINT] = 5.0
            worker.sensors_user_av[constants.SENSOR_USER_SENSOR_SQM_MAG] = 21.0
            worker.next_run = time.time() - 1  # ensure now >= next_run
        else:
            worker.sensor_q.put({'stop': True})

    with patch('time.sleep', side_effect=mock_sleep):
        worker.saferun()
        assert worker._shutdown is True


def test_sensor_worker_night_day_branches(sensor_worker_setup):
    worker = sensor_worker_setup
    worker.init_gpio()
    worker.init_dew_heater()
    worker.init_fan()

    # Night mode with FAN.ENABLE_NIGHT = False
    worker.config['FAN']['ENABLE_NIGHT'] = False
    worker.night = True
    with patch.object(worker, 'set_fan') as mock_set_fan:
        worker.night_day_change()
        mock_set_fan.assert_called_with(0)

    # Day mode with DEW_HEATER.ENABLE_DAY = True
    worker.config['DEW_HEATER']['ENABLE_DAY'] = True
    worker.dew_heater.state = 0
    worker.night = False
    with patch.object(worker, 'set_dew_heater') as mock_set_dh:
        worker.night_day_change()
        mock_set_dh.assert_called_with(worker.dh_level_default, force=True)


class CustomDevice:
    def __init__(self, exc=None):
        self.exc = exc
        self._state = 0

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, val):
        if self.exc:
            raise self.exc
        self._state = val



def test_sensor_worker_init_sensors_all_slots(sensor_worker_setup):
    worker = sensor_worker_setup
    from indi_allsky.devices.exceptions import DeviceControlException, SensorException
    import indi_allsky.devices.sensors as indi_allsky_sensors

    worker.config['TEMP_SENSOR'] = {
        'A_CLASSNAME': 'sensor_simulator',
        'A_LABEL': 'A',
        'A_USER_VAR_SLOT': 'sensor_user_10',
        'B_CLASSNAME': 'sensor_simulator',
        'B_LABEL': 'B',
        'B_USER_VAR_SLOT': 'sensor_user_20',
        'C_CLASSNAME': 'sensor_simulator',
        'C_LABEL': 'C',
        'C_USER_VAR_SLOT': 'sensor_user_30',
        'D_CLASSNAME': 'sensor_simulator',
        'D_LABEL': 'D',
        'D_USER_VAR_SLOT': 'sensor_user_40',
        'E_CLASSNAME': 'sensor_simulator',
        'E_LABEL': 'E',
        'E_USER_VAR_SLOT': 'sensor_user_50',
        'F_CLASSNAME': 'sensor_simulator',
        'F_LABEL': 'F',
        'F_USER_VAR_SLOT': 'sensor_user_55',
    }

    # 1. Successful initialization of all 6 sensors
    worker.init_sensors()
    assert len(worker.sensors) == 6
    assert worker.sensors[0].slot == 10
    assert worker.sensors[1].slot == 20
    assert worker.sensors[2].slot == 30
    assert worker.sensors[3].slot == 40
    assert worker.sensors[4].slot == 50
    assert worker.sensors[5].slot == 55

    # 2. Exception handling fallback in each sensor slot
    class FailingSensor:
        def __init__(self, *args, **kwargs):
            raise SensorException("Mock Sensor Fail")

    setattr(indi_allsky_sensors, 'failing_sensor_cls', FailingSensor)
    try:
        worker.config['TEMP_SENSOR'] = {
            'A_CLASSNAME': 'failing_sensor_cls',
            'B_CLASSNAME': 'failing_sensor_cls',
            'C_CLASSNAME': 'failing_sensor_cls',
            'D_CLASSNAME': 'failing_sensor_cls',
            'E_CLASSNAME': 'failing_sensor_cls',
            'F_CLASSNAME': 'failing_sensor_cls',
        }
        worker.init_sensors()
        assert len(worker.sensors) == 6
    finally:
        delattr(indi_allsky_sensors, 'failing_sensor_cls')



def test_sensor_worker_update_sensors(sensor_worker_setup):
    worker = sensor_worker_setup
    from indi_allsky.devices.exceptions import SensorReadException

    mock_sensor = MagicMock()
    mock_sensor.slot = 10
    mock_sensor.update.return_value = {
        'dew_point': 12.3,
        'frost_point': 8.1,
        'heat_index': 22.4,
        'wind_degrees': 180.0,
        'sqm_mag': 19.5,
        'rain': 1.0,
        'data': [1.1, 2.2],
    }
    worker.sensors = [mock_sensor]

    # 1. Update success
    worker.update_sensors()
    assert worker.sensors_user_av[constants.SENSOR_USER_DEW_POINT] == pytest.approx(12.3, 0.1)
    assert worker.sensors_user_av[constants.SENSOR_USER_FROST_POINT] == pytest.approx(8.1, 0.1)
    assert worker.sensors_user_av[constants.SENSOR_USER_HEAT_INDEX] == pytest.approx(22.4, 0.1)
    assert worker.sensors_user_av[constants.SENSOR_USER_WIND_DIR] == pytest.approx(180.0, 0.1)
    assert worker.sensors_user_av[constants.SENSOR_USER_SENSOR_SQM_MAG] == pytest.approx(19.5, 0.1)
    assert worker.sensors_user_av[constants.SENSOR_USER_RAIN] == pytest.approx(1.0, 0.1)
    assert worker.sensors_user_av[10] == pytest.approx(1.1, 0.1)
    assert worker.sensors_user_av[11] == pytest.approx(2.2, 0.1)

    # 2. Exceptions handled
    for exc in [SensorReadException("err"), OSError("err"), IOError("err"), IndexError("err")]:
        mock_sensor.update.side_effect = exc
        worker.update_sensors()  # should not raise


def test_sensor_worker_dew_heater_thresholds_branches(sensor_worker_setup):
    worker = sensor_worker_setup
    worker.init_dew_heater()

    # 1. THOLD_ENABLE = False
    worker.config['DEW_HEATER']['THOLD_ENABLE'] = False
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_not_called()

    worker.config['DEW_HEATER']['THOLD_ENABLE'] = True

    # 2. Not night and not ENABLE_DAY
    worker.night = False
    worker.config['DEW_HEATER']['ENABLE_DAY'] = False
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_not_called()

    # 3. Night mode, manual target
    worker.night = True
    worker.config['DEW_HEATER']['MANUAL_TARGET'] = 10.0
    worker.sensors_user_av[10] = 12.0  # delta = 2.0 <= diff_high (5)
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_called_with(worker.dh_level_high)

    # 4. Target dew point 0 warning and sensor_temp slot with display conversions
    worker.config['DEW_HEATER']['MANUAL_TARGET'] = 0.0
    worker.dh_dewpoint_slot = 'sensor_temp_0'
    worker.sensors_temp_av[0] = 0.0  # target 0

    worker.dh_temp_slot = 'sensor_temp_1'
    worker.sensors_temp_av[1] = 20.0

    # Fahrenheit display
    worker.config['TEMP_DISPLAY'] = 'f'
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()

    # Kelvin display
    worker.config['TEMP_DISPLAY'] = 'k'
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()

    # Celsius (else) display
    worker.config['TEMP_DISPLAY'] = 'c'
    # Medium threshold: diff_high < delta <= diff_med (e.g. delta = 8, diff_med = 10)
    worker.dh_dewpoint_slot = 'sensor_user_2'
    worker.dh_temp_slot = 'sensor_user_10'
    worker.sensors_user_av[2] = 10.0
    worker.sensors_user_av[10] = 18.0  # delta = 8
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_called_with(worker.dh_level_med)

    # Low threshold: diff_med < delta <= diff_low (e.g. delta = 13, diff_low = 15)
    worker.sensors_user_av[10] = 23.0  # delta = 13
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_called_with(worker.dh_level_low)

    # Default: delta > diff_low (e.g. delta = 20 > 15)
    worker.sensors_user_av[10] = 30.0  # delta = 20
    with patch.object(worker, 'set_dew_heater') as mock_set:
        worker.check_dew_heater_thresholds()
        mock_set.assert_called_with(worker.dh_level_default)


def test_sensor_worker_fan_thresholds_branches(sensor_worker_setup):
    worker = sensor_worker_setup
    worker.init_fan()

    # 1. THOLD_ENABLE = False
    worker.config['FAN']['THOLD_ENABLE'] = False
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_not_called()

    worker.config['FAN']['THOLD_ENABLE'] = True

    # 2. Night and not ENABLE_NIGHT
    worker.night = True
    worker.config['FAN']['ENABLE_NIGHT'] = False
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_not_called()

    worker.night = False

    # 3. fan_temp_slot starts with sensor_temp and display conversions
    worker.fan_temp_slot = 'sensor_temp_0'
    worker.sensors_temp_av[0] = 30.0

    worker.config['TEMP_DISPLAY'] = 'f'
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()

    worker.config['TEMP_DISPLAY'] = 'k'
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()

    # 4. Threshold ranges
    worker.config['TEMP_DISPLAY'] = 'c'
    worker.fan_temp_slot = 'sensor_user_10'
    worker.fan_target = 25.0
    worker.fan_thold_diff_high = 10.0
    worker.fan_thold_diff_med = 5.0
    worker.fan_thold_diff_low = 2.0

    # High: delta > diff_high (temp = 36, target = 25 -> delta = 11 > 10)
    worker.sensors_user_av[10] = 36.0
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_called_with(worker.fan_level_high)

    # Medium: diff_med < delta <= diff_high (temp = 32, delta = 7)
    worker.sensors_user_av[10] = 32.0
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_called_with(worker.fan_level_med)

    # Low: diff_low < delta <= diff_med (temp = 28, delta = 3)
    worker.sensors_user_av[10] = 28.0
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_called_with(worker.fan_level_low)

    # Default: delta <= diff_low (temp = 26, delta = 1)
    worker.sensors_user_av[10] = 26.0
    with patch.object(worker, 'set_fan') as mock_set:
        worker.check_fan_thresholds()
        mock_set.assert_called_with(worker.fan_level_default)

