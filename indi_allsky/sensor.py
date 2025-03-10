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
from .devices import sensors as indi_allsky_sensors
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
        night_v,
    ):
        super(SensorWorker, self).__init__()

        self.name = 'Sensor-{0:d}'.format(idx)

        self.config = config
        self.sensor_q = sensor_q
        self.error_q = error_q

        self.sensors_temp_av = sensors_temp_av
        self.sensors_user_av = sensors_user_av
        self.night_v = night_v
        self.night = False

        self.gpio = None
        self.dew_heater = None
        self.fan = None
        self.sensors = [None, None, None]

        self.next_run = time.time()  # run immediately
        self.next_run_offset = 15

        # dew heater
        self.dh_temp_slot = self.config.get('DEW_HEATER', {}).get('TEMP_USER_VAR_SLOT', 'sensor_user_10')
        self.dh_dewpoint_slot = self.config.get('DEW_HEATER', {}).get('DEWPOINT_USER_VAR_SLOT', 'sensor_user_2')

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

                return


            now = time.time()
            if not now >= self.next_run:
                continue


            # set next run
            self.next_run = now + self.next_run_offset

            #############################
            ### do interesting stuff here
            #############################


            if self.night != bool(self.night_v.value):
                self.night = bool(self.night_v.value)
                self.night_day_change()


            self.update_sensors()


            if self.sensors_user_av[2]:
                logger.info('Dew Point: %0.1f, Frost Point: %0.1f, Heat Index: %0.1f', self.sensors_user_av[2], self.sensors_user_av[3], self.sensors_user_av[5])


            if self.sensors_user_av[7]:
                logger.info('Sensor SQM: %0.5f', self.sensors_user_av[7])


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
                self.set_dew_heater(self.dh_level_default)


            # fan
            if self.config.get('FAN', {}).get('ENABLE_NIGHT'):
                if not self.fan.state:
                    self.set_fan(self.fan_level_default)
            else:
                self.set_fan(0)

        else:
            ### day

            # gpio
            self.set_gpio(0)


            # dew heater
            if self.config.get('DEW_HEATER', {}).get('ENABLE_DAY'):
                if not self.dew_heater.state:
                    self.set_dew_heater(self.dh_level_default)
            else:
                self.set_dew_heater(0)


            # fan
            if not self.fan.state:
                self.set_fan(self.fan_level_default)


    def init_gpio(self):
        a_gpio__classname = self.config.get('GENERIC_GPIO', {}).get('A_CLASSNAME')
        if a_gpio__classname:
            a_gpio_class = getattr(indi_allsky_gpios, a_gpio__classname)

            a_gpio_pin_1 = self.config.get('GENERIC_GPIO', {}).get('A_PIN_1', 'notdefined')
            a_gpio_invert_output = self.config.get('GENERIC_GPIO', {}).get('A_INVERT_OUTPUT', False)

            self.gpio = a_gpio_class(self.config, pin_1_name=a_gpio_pin_1, invert_output=a_gpio_invert_output)

            ### Do not set initial state on start

        else:
            self.gpio = indi_allsky_gpios.gpio_simulator(self.config)



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

            dh_pin_1 = self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined')
            dh_invert_output = self.config.get('DEW_HEATER', {}).get('INVERT_OUTPUT', False)

            self.dew_heater = dh_class(self.config, pin_1_name=dh_pin_1, invert_output=dh_invert_output)

            ### Do not set initial state on start

        else:
            self.dew_heater = dew_heaters.dew_heater_simulator(self.config)



    def set_dew_heater(self, new_state):
        if self.dew_heater.state != new_state:
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


            with self.sensors_user_av.get_lock():
                self.sensors_user_av[1] = float(self.dew_heater.state)


    def init_fan(self):
        fan_classname = self.config.get('FAN', {}).get('CLASSNAME')
        if fan_classname:
            fan_class = getattr(fans, fan_classname)

            fan_pin_1 = self.config.get('FAN', {}).get('PIN_1', 'notdefined')
            fan_invert_output = self.config.get('FAN', {}).get('INVERT_OUTPUT', False)

            self.fan = fan_class(self.config, pin_1_name=fan_pin_1, invert_output=fan_invert_output)

            ### Do not set initial state on start

        else:
            self.fan = fans.fan_simulator(self.config)


    def set_fan(self, new_state):
        if self.fan.state != new_state:
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


            with self.sensors_user_av.get_lock():
                self.sensors_user_av[4] = float(self.fan.state)


    def init_sensors(self):
        ### Sensor A
        a_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('A_CLASSNAME')
        if a_sensor_classname:
            a_sensor = getattr(indi_allsky_sensors, a_sensor_classname)

            a_sensor_label = self.config.get('TEMP_SENSOR', {}).get('A_LABEL', 'Sensor A')
            a_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('A_I2C_ADDRESS', '0x77')
            a_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('A_PIN_1', 'notdefined')

            try:
                self.sensors[0] = a_sensor(
                    self.config,
                    a_sensor_label,
                    self.night_v,
                    pin_1_name=a_sensor_pin_1_name,
                    i2c_address=a_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[0] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor A',
                    self.night_v,
                )
        else:
            self.sensors[0] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor A',
                self.night_v,
            )

        sensor_0_key = self.config.get('TEMP_SENSOR', {}).get('A_USER_VAR_SLOT', 'sensor_user_10')
        self.sensors[0].slot = constants.SENSOR_INDEX_MAP[sensor_0_key]


        ### Sensor B
        b_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('B_CLASSNAME')
        if b_sensor_classname:
            b_sensor = getattr(indi_allsky_sensors, b_sensor_classname)

            b_sensor_label = self.config.get('TEMP_SENSOR', {}).get('B_LABEL', 'Sensor B')
            b_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('B_I2C_ADDRESS', '0x76')
            b_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('B_PIN_1', 'notdefined')

            try:
                self.sensors[1] = b_sensor(
                    self.config,
                    b_sensor_label,
                    self.night_v,
                    pin_1_name=b_sensor_pin_1_name,
                    i2c_address=b_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[1] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor B',
                    self.night_v,
                )
        else:
            self.sensors[1] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor B',
                self.night_v,
            )

        sensor_1_key = self.config.get('TEMP_SENSOR', {}).get('B_USER_VAR_SLOT', 'sensor_user_15')
        self.sensors[1].slot = constants.SENSOR_INDEX_MAP[sensor_1_key]


        ### Sensor C
        c_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('C_CLASSNAME')
        if c_sensor_classname:
            c_sensor = getattr(indi_allsky_sensors, c_sensor_classname)

            c_sensor_label = self.config.get('TEMP_SENSOR', {}).get('C_LABEL', 'Sensor C')
            c_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('C_I2C_ADDRESS', '0x40')
            c_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('C_PIN_1', 'notdefined')

            try:
                self.sensors[2] = c_sensor(
                    self.config,
                    c_sensor_label,
                    self.night_v,
                    pin_1_name=c_sensor_pin_1_name,
                    i2c_address=c_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[2] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor B',
                    self.night_v,
                )
        else:
            self.sensors[2] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor B',
                self.night_v,
            )

        sensor_2_key = self.config.get('TEMP_SENSOR', {}).get('C_USER_VAR_SLOT', 'sensor_user_15')
        self.sensors[2].slot = constants.SENSOR_INDEX_MAP[sensor_2_key]


    def update_sensors(self):
        # update sensor readings
        for sensor in self.sensors:
            try:
                sensor_data = sensor.update()

                with self.sensors_user_av.get_lock():
                    if sensor_data.get('dew_point'):
                        self.sensors_user_av[2] = float(sensor_data['dew_point'])

                    if sensor_data.get('frost_point'):
                        self.sensors_user_av[3] = float(sensor_data['frost_point'])

                    if sensor_data.get('heat_index'):
                        self.sensors_user_av[5] = float(sensor_data['heat_index'])

                    if sensor_data.get('wind_degrees'):
                        self.sensors_user_av[6] = float(sensor_data['wind_degrees'])

                    if sensor_data.get('sqm_mag'):
                        self.sensors_user_av[7] = float(sensor_data['sqm_mag'])


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
            if str(self.dh_temp_slot).startswith('sensor_temp'):
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
        logger.info('Dew Heater threshold current: %0.1f, target: %0.1f, delta: %0.1f (%0.0f%%)', current_temp, target_val, dh_temp_delta, self.dew_heater.state)

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
        logger.info('Fan threshold current: %0.1f, target: %0.1f, delta: %0.1f (%0.0f%%)', current_temp, self.fan_target, fan_temp_delta, self.fan.state)

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

