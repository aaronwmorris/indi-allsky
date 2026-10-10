import time
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from indi_allsky.sensor import SensorWorker
from indi_allsky import constants
from indi_allsky.devices import generic as indi_allsky_gpios
from indi_allsky.devices import dew_heaters
from indi_allsky.devices import fans
from indi_allsky.devices import sensors as indi_allsky_sensors
from indi_allsky.devices.exceptions import (
    DeviceControlException,
    SensorException,
    SensorReadException,
)


class CustomIOError(Exception):
    pass


class StateMock:
    def __init__(self, exc=None):
        self._state = 0
        self.exc = exc

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, val):
        if self.exc:
            raise self.exc
        self._state = val


def create_worker(config_updates=None):
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
            'HOLD_SECONDS': 100,
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
            'HOLD_SECONDS': 100,
            'TARGET': 25.0,
            'TEMP_USER_VAR_SLOT': 'sensor_user_10',
        },
        'GPIO': {
            'CLASSNAME': 'gpio_simulator',
        },
    }
    if config_updates:
        for k, v in config_updates.items():
            if isinstance(v, dict) and k in config:
                config[k].update(v)
            else:
                config[k] = v

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


def test_init_gpio_configured_and_exceptions():
    # 1. Successful initialization with A_CLASSNAME (lines 266-278)
    worker = create_worker({'GENERIC_GPIO': {'A_CLASSNAME': 'gpio_simulator'}})
    worker.init_gpio()
    assert worker.gpio is not None

    # 2. OSError / ValueError during init (lines 279-281)
    failing_cls = MagicMock(side_effect=OSError("GPIO HW error"))
    with patch.dict(indi_allsky_gpios.__dict__, {'failing_gpio_oserror': failing_cls}):
        worker = create_worker({'GENERIC_GPIO': {'A_CLASSNAME': 'failing_gpio_oserror'}})
        worker.init_gpio()
        assert worker.gpio is not None

    # 3. DeviceControlException during init (lines 282-284)
    failing_ctrl_cls = MagicMock(side_effect=DeviceControlException("GPIO control error"))
    with patch.dict(indi_allsky_gpios.__dict__, {'failing_gpio_ctrl': failing_ctrl_cls}):
        worker = create_worker({'GENERIC_GPIO': {'A_CLASSNAME': 'failing_gpio_ctrl'}})
        worker.init_gpio()
        assert worker.gpio is not None


def test_set_gpio_exceptions():
    worker = create_worker()
    worker.init_gpio()

    # DeviceControlException (lines 298-300)
    worker.gpio = StateMock(exc=DeviceControlException("Failed"))
    worker.set_gpio(1)

    # OSError (lines 301-303)
    worker.gpio = StateMock(exc=OSError("OS error"))
    worker.set_gpio(1)

    # IOError (lines 304-306)
    worker.gpio = StateMock(exc=CustomIOError("IO error"))
    with patch('indi_allsky.sensor.IOError', CustomIOError):
        worker.set_gpio(1)


def test_init_dew_heater_exceptions_and_empty():
    # Empty CLASSNAME -> falls into else (line 335)
    worker_empty = create_worker({'DEW_HEATER': {'CLASSNAME': ''}})
    worker_empty.init_dew_heater()
    assert worker_empty.dew_heater is not None

    # OSError / ValueError during init (lines 327-330)
    failing_dh_val = MagicMock(side_effect=ValueError("Invalid I2C address"))
    with patch.dict(dew_heaters.__dict__, {'failing_dh_val': failing_dh_val}):
        worker = create_worker({'DEW_HEATER': {'CLASSNAME': 'failing_dh_val'}})
        worker.init_dew_heater()
        assert worker.dew_heater is not None

    # DeviceControlException during init (lines 331-333)
    failing_dh_ctrl = MagicMock(side_effect=DeviceControlException("Control failed"))
    with patch.dict(dew_heaters.__dict__, {'failing_dh_ctrl': failing_dh_ctrl}):
        worker = create_worker({'DEW_HEATER': {'CLASSNAME': 'failing_dh_ctrl'}})
        worker.init_dew_heater()
        assert worker.dew_heater is not None


def test_set_dew_heater_hold_and_exceptions():
    worker = create_worker()
    worker.init_dew_heater()

    # Test hold seconds when not force (lines 348-349)
    worker.dh_last_change_time = time.time() + 1000
    worker.dh_hold_seconds = 500
    worker.set_dew_heater(50, force=False)
    assert worker.dew_heater.state == 0

    worker.dh_last_change_time = 0

    # DeviceControlException (lines 354-356)
    worker.dew_heater = StateMock(exc=DeviceControlException("DH Fail"))
    worker.set_dew_heater(10, force=True)

    # OSError (lines 357-359)
    worker.dew_heater = StateMock(exc=OSError("DH OS Fail"))
    worker.set_dew_heater(10, force=True)

    # IOError (lines 360-362)
    worker.dew_heater = StateMock(exc=CustomIOError("DH IO Fail"))
    with patch('indi_allsky.sensor.IOError', CustomIOError):
        worker.set_dew_heater(10, force=True)


def test_init_fan_exceptions_and_empty():
    # Empty CLASSNAME -> falls into else (line 397)
    worker_empty = create_worker({'FAN': {'CLASSNAME': ''}})
    worker_empty.init_fan()
    assert worker_empty.fan is not None

    # OSError / ValueError during init (lines 389-391)
    failing_fan_val = MagicMock(side_effect=ValueError("Invalid fan freq"))
    with patch.dict(fans.__dict__, {'failing_fan_val': failing_fan_val}):
        worker = create_worker({'FAN': {'CLASSNAME': 'failing_fan_val'}})
        worker.init_fan()
        assert worker.fan is not None

    # DeviceControlException during init (lines 392-395)
    failing_fan_ctrl = MagicMock(side_effect=DeviceControlException("Fan init failed"))
    with patch.dict(fans.__dict__, {'failing_fan_ctrl': failing_fan_ctrl}):
        worker = create_worker({'FAN': {'CLASSNAME': 'failing_fan_ctrl'}})
        worker.init_fan()
        assert worker.fan is not None


def test_set_fan_hold_and_exceptions():
    worker = create_worker()
    worker.init_fan()

    # Test hold seconds when not force (lines 410-411)
    worker.fan_last_change_time = time.time() + 1000
    worker.fan_hold_seconds = 500
    worker.set_fan(50, force=False)
    assert worker.fan.state == 0

    worker.fan_last_change_time = 0

    # DeviceControlException (lines 416-418)
    worker.fan = StateMock(exc=DeviceControlException("Fan Fail"))
    worker.set_fan(10, force=True)

    # OSError (lines 419-421)
    worker.fan = StateMock(exc=OSError("Fan OS Fail"))
    worker.set_fan(10, force=True)

    # IOError (lines 422-424)
    worker.fan = StateMock(exc=CustomIOError("Fan IO Fail"))
    with patch('indi_allsky.sensor.IOError', CustomIOError):
        worker.set_fan(10, force=True)


def test_init_sensors_empty_a_classname():
    # A_CLASSNAME empty -> falls into else (line 463)
    worker = create_worker({'TEMP_SENSOR': {'A_CLASSNAME': ''}})
    worker.init_sensors()
    assert worker.sensors[0] is not None


def test_update_sensors_ioerror():
    # IOError during sensor update (line 707)
    worker = create_worker()
    worker.init_sensors()
    worker.sensors[0].update = MagicMock(side_effect=CustomIOError("Bus error"))
    with patch('indi_allsky.sensor.IOError', CustomIOError):
        worker.update_sensors()


def test_check_thresholds_temp_display_celsius():
    # Lines 743 and 786: TEMP_DISPLAY is default/Celsius ('c' or not set) with sensor_temp slot
    worker = create_worker({
        'TEMP_DISPLAY': 'c',
        'DEW_HEATER': {
            'CLASSNAME': 'dew_heater_simulator',
            'THOLD_ENABLE': True,
            'ENABLE_DAY': True,
            'HOLD_SECONDS': 0,
            'TEMP_USER_VAR_SLOT': 'sensor_temp_0',
            'DEWPOINT_USER_VAR_SLOT': 'sensor_temp_1',
            'THOLD_DIFF_LOW': 15,
            'THOLD_DIFF_MED': 10,
            'THOLD_DIFF_HIGH': 5,
        },
        'FAN': {
            'CLASSNAME': 'fan_simulator',
            'THOLD_ENABLE': True,
            'ENABLE_NIGHT': True,
            'HOLD_SECONDS': 0,
            'TEMP_USER_VAR_SLOT': 'sensor_temp_0',
            'TARGET': 20.0,
            'THOLD_DIFF_LOW': 5,
            'THOLD_DIFF_MED': 10,
            'THOLD_DIFF_HIGH': 15,
        },
    })
    worker.night = True
    worker.init_dew_heater()
    worker.init_fan()

    worker.dh_temp_slot = 'sensor_temp_0'
    worker.dh_dewpoint_slot = 'sensor_temp_1'
    worker.fan_temp_slot = 'sensor_temp_0'

    worker.sensors_temp_av[constants.SENSOR_INDEX_MAP['sensor_temp_0']] = 15.0
    worker.sensors_temp_av[constants.SENSOR_INDEX_MAP['sensor_temp_1']] = 10.0

    worker.check_dew_heater_thresholds()
    worker.check_fan_thresholds()


def test_sensor_worker_saferun_next_run_continue():
    # Line 184: now < next_run -> continue
    worker = create_worker()
    worker.init_gpio()
    worker.init_dew_heater()
    worker.init_fan()
    worker.init_sensors()
    worker.next_run = time.time() + 1000

    loop_count = [0]
    def mock_sleep(s):
        loop_count[0] += 1
        if loop_count[0] == 1:
            # First iteration: next_run is in future, triggers line 184 continue
            pass
        else:
            # Second iteration: stop worker
            worker.sensor_q.put({'stop': True})

    with patch('time.sleep', side_effect=mock_sleep):
        worker.saferun()
        assert worker._shutdown is True

