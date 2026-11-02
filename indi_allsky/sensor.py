import time
import signal
import traceback
import logging

#from threading import Thread
import queue
#import threading

from multiprocessing import Process

from . import constants

from .devices import generic as indi_allsky_gpios
from .devices import dew_heaters
from .devices import fans
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
        self.sensors = [None, None, None, None, None, None]

        self.next_run = time.time()  # run immediately
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

                for sensor in self.sensors:
                    sensor.deinit()

                return


            now = time.time()
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
        from .sensor_slots import initialize_sensors

        self.sensors = initialize_sensors(self.config, self.night_av, self.astro_av)


    def update_sensors(self):
        # update sensor readings
        for sensor in self.sensors:
            try:
                sensor_data = sensor.update()

                with self.sensors_user_av.get_lock():
                    if not isinstance(sensor_data.get('dew_point'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_DEW_POINT] = float(sensor_data['dew_point'])

                    if not isinstance(sensor_data.get('frost_point'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_FROST_POINT] = float(sensor_data['frost_point'])

                    if not isinstance(sensor_data.get('heat_index'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_HEAT_INDEX] = float(sensor_data['heat_index'])

                    if not isinstance(sensor_data.get('wind_degrees'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_WIND_DIR] = float(sensor_data['wind_degrees'])

                    if not isinstance(sensor_data.get('sqm_mag'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_SENSOR_SQM_MAG] = float(sensor_data['sqm_mag'])

                    if not isinstance(sensor_data.get('rain'), type(None)):
                        self.sensors_user_av[constants.SENSOR_USER_RAIN] = float(sensor_data['rain'])


                    for i, v in enumerate(sensor_data['data']):
                        self.sensors_user_av[sensor.slot + i] = float(v)
            except SensorReadException as e:
                logger.error('SensorReadException: {0:s}'.format(str(e)))
            except OSError as e:
                logger.error('Sensor OSError: {0:s}'.format(str(e)))
            except IOError as e:
                logger.error('Sensor IOError: {0:s}'.format(str(e)))
            except IndexError as e:
                logger.error('Sensor slot error: {0:s}'.format(str(e)))


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
