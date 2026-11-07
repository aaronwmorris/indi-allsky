import time
import signal
import traceback
import logging
import math

#from threading import Thread
import queue
#import threading

from multiprocessing import Process

from . import constants
from .sensor_health import SensorHealth, SensorRetry

from .devices import generic as indi_allsky_gpios
from .devices import dew_heaters
from .devices import fans
from .devices import sensors as indi_allsky_sensors
from .devices.exceptions import SensorException
from .devices.exceptions import SensorReadException
from .devices.exceptions import DeviceControlException

logger = logging.getLogger('indi_allsky')


### lgpio module appears to not be thread safe when using with multiprocessing

class SensorWorker(Process):
    def __init__(
        self,
        idx,
        config,
        sensor_q,
        error_q,
        sensors_temp_av,
        sensors_user_av,
        night_av,
        astro_av,
        sensor_health=None,
    ):
        super(SensorWorker, self).__init__()

        self.name = 'Sensor-{0:d}'.format(idx)

        self.config = config
        self.sensor_q = sensor_q
        self.error_q = error_q

        self.sensors_temp_av = sensors_temp_av
        self.sensors_user_av = sensors_user_av
        self.astro_av = astro_av
        self.night_av = night_av
        self.night = None  # None forces day/night change at startup

        self.gpio = None
        self.dew_heater = None
        self.fan = None
        self.sensors = [None] * 6
        self.sensor_health = sensor_health if sensor_health is not None else SensorHealth()
        self.retries = [SensorRetry() for _ in self.sensors]

        self.next_run = time.monotonic()  # run immediately
        self.next_run_offset = 15

        # dew heater
        self.dh_temp_slot = self.config.get('DEW_HEATER', {}).get('TEMP_USER_VAR_SLOT', 'sensor_user_10')
        self.dh_dewpoint_slot = self.config.get('DEW_HEATER', {}).get('DEWPOINT_USER_VAR_SLOT', 'sensor_user_2')
        self.dh_hold_seconds = self.config.get('DEW_HEATER', {}).get('HOLD_SECONDS', 0)
        self.dh_last_change_time = 0

        self.dh_level_default = self.config.get('DEW_HEATER', {}).get('LEVEL_DEF', 0)
        self.dh_level_low = self.config.get('DEW_HEATER', {}).get('LEVEL_LOW', 33)
        self.dh_level_med = self.config.get('DEW_HEATER', {}).get('LEVEL_MED', 66)
        self.dh_level_high = self.config.get('DEW_HEATER', {}).get('LEVEL_HIGH', 100)

        self.dh_thold_diff_low = self.config.get('DEW_HEATER', {}).get('THOLD_DIFF_LOW', 15)
        self.dh_thold_diff_med = self.config.get('DEW_HEATER', {}).get('THOLD_DIFF_MED', 10)
        self.dh_thold_diff_high = self.config.get('DEW_HEATER', {}).get('THOLD_DIFF_HIGH', 5)


        # fan
        self.fan_target = self.config.get('FAN', {}).get('TARGET', 30.0)
        self.fan_temp_slot = self.config.get('FAN', {}).get('TEMP_USER_VAR_SLOT', 'sensor_user_10')
        self.fan_hold_seconds = self.config.get('FAN', {}).get('HOLD_SECONDS', 0)
        self.fan_last_change_time = 0

        self.fan_level_default = self.config.get('FAN', {}).get('LEVEL_DEF', 0)
        self.fan_level_low = self.config.get('FAN', {}).get('LEVEL_LOW', 33)
        self.fan_level_med = self.config.get('FAN', {}).get('LEVEL_MED', 66)
        self.fan_level_high = self.config.get('FAN', {}).get('LEVEL_HIGH', 100)

        self.fan_thold_diff_low = self.config.get('FAN', {}).get('THOLD_DIFF_LOW', -10)
        self.fan_thold_diff_med = self.config.get('FAN', {}).get('THOLD_DIFF_MED', -5)
        self.fan_thold_diff_high = self.config.get('FAN', {}).get('THOLD_DIFF_HIGH', 0)

        self._shutdown = False
        #self._stopper = threading.Event()


    #def stop(self):
    #    self._stopper.set()


    #def stopped(self):
    #    return self._stopper.is_set()


    def sighup_handler_worker(self, signum, frame):
        logger.warning('Caught HUP signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigterm_handler_worker(self, signum, frame):
        logger.warning('Caught TERM signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigint_handler_worker(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def run(self):
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGHUP, self.sighup_handler_worker)
        signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        signal.signal(signal.SIGINT, self.sigint_handler_worker)
        #signal.signal(signal.SIGALRM, self.sigalarm_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e


    def saferun(self):
        #raise Exception('Test exception handling in worker')

        self.init_sensors()  # sensors before dew heater and fan
        self.update_sensors()

        self.init_gpio()
        self.init_dew_heater()
        self.init_fan()


        while True:
            time.sleep(3)

            try:
                s_dict = self.sensor_q.get(False)

                if s_dict.get('stop'):
                    self._shutdown = True
                else:
                    logger.error('Unknown action: %s', str(s_dict))

            except queue.Empty:
                pass


            if self._shutdown:
                logger.warning('Goodbye')

                # deinit devices
                self.gpio.deinit()
                self.fan.deinit()
                self.dew_heater.deinit()

                for i in range(len(self.sensors)):
                    self._close_sensor(i)

                return


            now = time.monotonic()
            if not now >= self.next_run:
                continue


            # set next run
            self.next_run = now + self.next_run_offset

            #############################
            ### do interesting stuff here
            #############################


            if self.night != bool(self.night_av[constants.NIGHT_NIGHT]):
                self.night = bool(self.night_av[constants.NIGHT_NIGHT])
                self.night_day_change()


            self.update_sensors()


            if self.sensors_user_av[constants.SENSOR_USER_DEW_POINT]:
                logger.info(
                    'Dew Point: %0.1f, Frost Point: %0.1f, Heat Index: %0.1f',
                    self.sensors_user_av[constants.SENSOR_USER_DEW_POINT],
                    self.sensors_user_av[constants.SENSOR_USER_FROST_POINT],
                    self.sensors_user_av[constants.SENSOR_USER_HEAT_INDEX],
                )


            if self.sensors_user_av[constants.SENSOR_USER_SENSOR_SQM_MAG]:
                logger.info('Sensor SQM Magnitude: %0.5f', self.sensors_user_av[constants.SENSOR_USER_SENSOR_SQM_MAG])


            self.check_dew_heater_thresholds()
            self.check_fan_thresholds()


    def night_day_change(self):
        logger.warning('Day/Night change')

        # changing modes here
        if self.night:
            ### night

            # gpio
            self.set_gpio(1)


            # dew heater
            if not self.dew_heater.state:
                self.set_dew_heater(self.dh_level_default, force=True)


            # fan
            if self.config.get('FAN', {}).get('ENABLE_NIGHT'):
                if not self.fan.state:
                    self.set_fan(self.fan_level_default, force=True)
            else:
                self.set_fan(0)

        else:
            ### day

            # gpio
            self.set_gpio(0)


            # dew heater
            if self.config.get('DEW_HEATER', {}).get('ENABLE_DAY'):
                if not self.dew_heater.state:
                    self.set_dew_heater(self.dh_level_default, force=True)
            else:
                self.set_dew_heater(0)


            # fan
            if not self.fan.state:
                self.set_fan(self.fan_level_default, force=True)


    def init_gpio(self):
        a_gpio__classname = self.config.get('GENERIC_GPIO', {}).get('A_CLASSNAME')
        if a_gpio__classname:
            a_gpio_class = getattr(indi_allsky_gpios, a_gpio__classname)

            a_gpio_i2c_address = self.config.get('GENERIC_GPIO', {}).get('A_I2C_ADDRESS', '0x12')
            a_gpio_pin_1 = self.config.get('GENERIC_GPIO', {}).get('A_PIN_1', 'notdefined')
            a_gpio_invert_output = self.config.get('GENERIC_GPIO', {}).get('A_INVERT_OUTPUT', False)

            try:
                self.gpio = a_gpio_class(
                    self.config,
                    i2c_address=a_gpio_i2c_address,
                    pin_1_name=a_gpio_pin_1,
                    invert_output=a_gpio_invert_output,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing gpio controller: %s', str(e))
                self.gpio = indi_allsky_gpios.gpio_simulator(self.config)
            except DeviceControlException as e:
                logger.error('Error initializing gpio controller: %s', str(e))
                self.gpio = indi_allsky_gpios.gpio_simulator(self.config)

        else:
            self.gpio = indi_allsky_gpios.gpio_simulator(self.config)


        # set initial state
        self.gpio.state = 0


    def set_gpio(self, new_state):
        if self.gpio.state != new_state:
            try:
                self.gpio.state = new_state
            except DeviceControlException as e:
                logger.error('GPIO exception: %s', str(e))
                return
            except OSError as e:
                logger.error('GPIO OSError: %s', str(e))
                return
            except IOError as e:
                logger.error('GPIO IOError: %s', str(e))
                return


    def init_dew_heater(self):
        dew_heater_classname = self.config.get('DEW_HEATER', {}).get('CLASSNAME')
        if dew_heater_classname:
            dh_class = getattr(dew_heaters, dew_heater_classname)

            dh_i2c_address = self.config.get('DEW_HEATER', {}).get('I2C_ADDRESS', '0x10')
            dh_pin_1 = self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined')
            dh_invert_output = self.config.get('DEW_HEATER', {}).get('INVERT_OUTPUT', False)
            dh_pwm_frequency = self.config.get('DEW_HEATER', {}).get('PWM_FREQUENCY', 500)

            try:
                self.dew_heater = dh_class(
                    self.config,
                    i2c_address=dh_i2c_address,
                    pin_1_name=dh_pin_1,
                    invert_output=dh_invert_output,
                    pwm_frequency=dh_pwm_frequency,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing dew heater controller: %s', str(e))
                self.dew_heater = dew_heaters.dew_heater_simulator(self.config)
            except DeviceControlException as e:
                logger.error('Error initializing dew heater controller: %s', str(e))
                self.dew_heater = dew_heaters.dew_heater_simulator(self.config)

        else:
            self.dew_heater = dew_heaters.dew_heater_simulator(self.config)


        # set initial state
        self.dew_heater.state = 0


    def set_dew_heater(self, new_state, force=False):
        if self.dew_heater.state != new_state:
            now_time = time.time()

            if not force:
                if self.dh_last_change_time > (now_time - self.dh_hold_seconds):
                    logger.info('Dew Heater will hold for an additional %ds', int(self.dh_last_change_time - (now_time - self.dh_hold_seconds)))
                    return


            try:
                self.dew_heater.state = new_state
            except DeviceControlException as e:
                logger.error('Dew heater exception: %s', str(e))
                return
            except OSError as e:
                logger.error('Dew heater OSError: %s', str(e))
                return
            except IOError as e:
                logger.error('Dew heater IOError: %s', str(e))
                return


            self.dh_last_change_time = now_time

            with self.sensors_user_av.get_lock():
                self.sensors_user_av[constants.SENSOR_USER_DEW_HEATER_LEVEL] = float(self.dew_heater.state)


    def init_fan(self):
        fan_classname = self.config.get('FAN', {}).get('CLASSNAME')
        if fan_classname:
            fan_class = getattr(fans, fan_classname)

            fan_i2c_address = self.config.get('FAN', {}).get('I2C_ADDRESS', '0x11')
            fan_pin_1 = self.config.get('FAN', {}).get('PIN_1', 'notdefined')
            fan_invert_output = self.config.get('FAN', {}).get('INVERT_OUTPUT', False)
            fan_pwm_frequency = self.config.get('FAN', {}).get('PWM_FREQUENCY', 500)

            try:
                self.fan = fan_class(
                    self.config,
                    i2c_address=fan_i2c_address,
                    pin_1_name=fan_pin_1,
                    invert_output=fan_invert_output,
                    pwm_frequency=fan_pwm_frequency,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing fan controller: %s', str(e))
                self.fan = fans.fan_simulator(self.config)
            except DeviceControlException as e:
                logger.error('Error initializing fan controller: %s', str(e))
                self.fan = fans.fan_simulator(self.config)

        else:
            self.fan = fans.fan_simulator(self.config)


        # set initial state
        self.fan.state = 0


    def set_fan(self, new_state, force=False):
        if self.fan.state != new_state:
            now_time = time.time()

            if not force:
                if self.fan_last_change_time > (now_time - self.fan_hold_seconds):
                    logger.info('Fan will hold for an additional %ds', int(self.fan_last_change_time - (now_time - self.fan_hold_seconds)))
                    return


            try:
                self.fan.state = new_state
            except DeviceControlException as e:
                logger.error('Fan exception: %s', str(e))
                return
            except OSError as e:
                logger.error('Fan OSError: %s', str(e))
                return
            except IOError as e:
                logger.error('Fan IOError: %s', str(e))
                return


            self.fan_last_change_time = now_time

            with self.sensors_user_av.get_lock():
                self.sensors_user_av[constants.SENSOR_USER_FAN_LEVEL] = float(self.fan.state)


    def init_sensors(self):
        # Retain the configured driver (even when the first opening fails).
        # Each device has its own retry deadline; no sleep delays the next one.
        self.sensor_specs = []
        cfg = self.config.get('TEMP_SENSOR', {})
        for i, letter in enumerate('ABCDEF'):
            name = cfg.get(letter + '_CLASSNAME') or 'sensor_simulator'
            factory = getattr(indi_allsky_sensors, name, None)
            address = cfg.get(letter + '_I2C_ADDRESS', ('0x77', '0x76', '0x40', '0x50', '0x51', '0x52')[i])
            key = cfg.get(letter + '_USER_VAR_SLOT', 'sensor_user_{}'.format((10, 20, 30, 40, 50, 55)[i]))
            if factory is None or key not in constants.SENSOR_INDEX_MAP:
                logger.error('Invalid sensor %s driver or slot: %s, %s', letter, name, key)
                factory = indi_allsky_sensors.sensor_simulator
            slot = constants.SENSOR_INDEX_MAP.get(key, 0)
            spec = (factory, cfg.get(letter + '_LABEL', 'Sensor ' + letter), slot,
                    dict(pin_1_name=cfg.get(letter + '_PIN_1', 'notdefined'),
                         pin_2_name=cfg.get(letter + '_PIN_2', 'notdefined'), i2c_address=address))
            self.sensor_specs.append(spec)
            with self.sensors_user_av.get_lock():
                self.sensor_health.invalidate(slot, factory.METADATA['count'])


    def _close_sensor(self, i):
        sensor, self.sensors[i] = self.sensors[i], None
        if sensor is not None:
            try:
                sensor.deinit()
            except Exception as exc:
                logger.warning('%s cleanup failed: %s', sensor.name, exc)


    def _write_sample(self, i, sensor, result, now):
        if result.get('sample_disabled'):
            with self.sensors_user_av.get_lock():
                self.sensor_health.invalidate(sensor.slot, sensor.METADATA['count'])
            return
        values = tuple(float(x) if x is not None else None for x in result['data'])
        if not values:
            # Some drivers deliberately return an empty cache until warmed up.
            return
        if len(values) > sensor.METADATA['count'] or sensor.slot + len(values) > len(self.sensors_user_av):
            raise SensorReadException('Reading exceeds configured sensor channels')
        # Drivers with a slower polling cadence return the previous result
        # object between actual measurements. Its timestamp must not advance.
        if result is self.retries[i].previous_sample:
            return
        fresh_for = max(60, 2 * getattr(sensor, 'next_run_offset', 0) + self.next_run_offset)
        stamps = result.get('observed', [now] * len(values))
        if len(stamps) != len(values):
            raise SensorReadException('Missing per-channel measurement timestamps')
        derived = ((constants.SENSOR_USER_DEW_POINT, 'dew_point'),
                   (constants.SENSOR_USER_FROST_POINT, 'frost_point'),
                   (constants.SENSOR_USER_HEAT_INDEX, 'heat_index'),
                   (constants.SENSOR_USER_WIND_DIR, 'wind_degrees'),
                   (constants.SENSOR_USER_SENSOR_SQM_MAG, 'sqm_mag'),
                   (constants.SENSOR_USER_RAIN, 'rain'))
        had_sample = False
        with self.sensors_user_av.get_lock():
            self.sensor_health.invalidate(sensor.slot, sensor.METADATA['count'])
            for j, (value, stamp) in enumerate(zip(values, stamps)):
                if value is None or not math.isfinite(value) or stamp <= 0:
                    continue
                self.sensors_user_av[sensor.slot + j] = value
                self.sensor_health.expires[sensor.slot + j] = stamp + fresh_for
                if stamp + fresh_for > now:
                    had_sample = True
            if had_sample:
                for slot, key in derived:
                    value = result.get(key)
                    if value is not None and math.isfinite(float(value)):
                        self.sensors_user_av[slot] = float(value)
                # Store the timestamp of the observation, not repeated polls of
                # async devices such as MQTT.
                newest = max(stamp for value, stamp in zip(values, stamps)
                             if value is not None and math.isfinite(value) and stamp > 0)
                self.sensor_health.last_good[i] = int(time.time() - max(0, now - newest))
                self.retries[i].last_observed = newest
        self.retries[i].previous_sample = result
        if had_sample:
            self.retries[i].success()


    def update_sensors(self):
        for i, (factory, label, slot, options) in enumerate(self.sensor_specs):
            if factory.METADATA['count'] == 0:
                continue  # disabled/empty simulator is not a failing sensor
            retry = self.retries[i]
            now = time.monotonic()
            if now < retry.next_open:
                continue
            try:
                if self.sensors[i] is None:
                    sensor = factory(self.config, label, self.night_av, self.astro_av, **options)
                    sensor.slot = slot
                    self.sensors[i] = sensor
                    retry.last_observed = time.monotonic()  # grace for warming up
                sensor = self.sensors[i]
                result = sensor.update()
                completed = time.monotonic()
                self._write_sample(i, sensor, result, completed)
                if result.get('sample_disabled'):
                    # An explicitly disabled sensor is not a failed device.
                    retry.last_observed = completed
                    retry.success()
                elif completed - retry.last_observed > max(60, 2 * getattr(sensor, 'next_run_offset', 0) + self.next_run_offset):
                    raise SensorReadException('No new measurement within the expected interval')
            except (SensorException, SensorReadException, DeviceControlException, OSError,
                    ValueError, RuntimeError, IndexError, TypeError, OverflowError, ImportError) as exc:
                with self.sensors_user_av.get_lock():
                    self.sensor_health.invalidate(slot, factory.METADATA['count'])
                retry.failures += 1
                logger.error('Sensor %s (%s) failed: %s', 'ABCDEF'[i], label, exc)
                if self.sensors[i] is None or retry.failures >= 3:
                    self._close_sensor(i)
                    retry.retry_later(time.monotonic())
                    logger.warning('Retrying sensor %s (%s) in %ds', 'ABCDEF'[i], label,
                                   round(retry.next_open - time.monotonic()))


    def check_dew_heater_thresholds(self):
        # dew heater threshold processing
        if not self.config.get('DEW_HEATER', {}).get('THOLD_ENABLE'):
            return


        if not self.night and not self.config.get('DEW_HEATER', {}).get('ENABLE_DAY'):
            return


        manual_target = self.config.get('DEW_HEATER', {}).get('MANUAL_TARGET', 0.0)
        if manual_target:
            target_val = manual_target
        else:
            if str(self.dh_dewpoint_slot).startswith('sensor_temp'):
                target_val = self.sensors_temp_av[constants.SENSOR_INDEX_MAP[self.dh_dewpoint_slot]]  # dew point
            else:
                target_val = self.sensors_user_av[constants.SENSOR_INDEX_MAP[self.dh_dewpoint_slot]]  # dew point

        if not target_val:
            logger.warning('Dew heater target dew point is 0, possible misconfiguration')


        if str(self.dh_temp_slot).startswith('sensor_temp'):
            current_temp = self.sensors_temp_av[constants.SENSOR_INDEX_MAP[self.dh_temp_slot]]

            if self.config.get('TEMP_DISPLAY') == 'f':
                current_temp = (current_temp * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                current_temp = current_temp + 273.15
            else:
                pass
        else:
            current_temp = self.sensors_user_av[constants.SENSOR_INDEX_MAP[self.dh_temp_slot]]


        dh_temp_delta = current_temp - target_val


        if dh_temp_delta <= self.dh_thold_diff_high:
            # set dew heater to high
            self.set_dew_heater(self.dh_level_high)
        elif dh_temp_delta <= self.dh_thold_diff_med:
            # set dew heater to medium
            self.set_dew_heater(self.dh_level_med)
        elif dh_temp_delta <= self.dh_thold_diff_low:
            # set dew heater to low
            self.set_dew_heater(self.dh_level_low)
        else:
            self.set_dew_heater(self.dh_level_default)
            #self.set_dew_heater(0)


        logger.info('Dew Heater threshold current: %0.1f, target: %0.1f, delta: %0.1f (%0.0f%%)', current_temp, target_val, dh_temp_delta, self.dew_heater.state)


    def check_fan_thresholds(self):
        # fan threshold processing
        if not self.config.get('FAN', {}).get('THOLD_ENABLE'):
            return


        if self.night and not self.config.get('FAN', {}).get('ENABLE_NIGHT'):
            return


        if str(self.fan_temp_slot).startswith('sensor_temp'):
            current_temp = self.sensors_temp_av[constants.SENSOR_INDEX_MAP[self.fan_temp_slot]]

            if self.config.get('TEMP_DISPLAY') == 'f':
                current_temp = (current_temp * 9.0 / 5.0) + 32
            elif self.config.get('TEMP_DISPLAY') == 'k':
                current_temp = current_temp + 273.15
            else:
                pass
        else:
            current_temp = self.sensors_user_av[constants.SENSOR_INDEX_MAP[self.fan_temp_slot]]


        fan_temp_delta = current_temp - self.fan_target


        if fan_temp_delta > self.fan_thold_diff_high:
            # set fan to high
            self.set_fan(self.fan_level_high)
        elif fan_temp_delta > self.fan_thold_diff_med:
            # set fan to medium
            self.set_fan(self.fan_level_med)
        elif fan_temp_delta > self.fan_thold_diff_low:
            # set fan to low
            self.set_fan(self.fan_level_low)
        else:
            self.set_fan(self.fan_level_default)
            #self.set_fan(0)


        logger.info('Fan threshold current: %0.1f, target: %0.1f, delta: %0.1f (%0.0f%%)', current_temp, self.fan_target, fan_temp_delta, self.fan.state)
