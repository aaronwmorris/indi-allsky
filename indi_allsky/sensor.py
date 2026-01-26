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
                self.sensors_user_av[1] = float(self.dew_heater.state)


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
                self.sensors_user_av[4] = float(self.fan.state)


    def init_sensors(self):
        ### Sensor A
        a_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('A_CLASSNAME')
        if a_sensor_classname:
            a_sensor = getattr(indi_allsky_sensors, a_sensor_classname)

            a_sensor_label = self.config.get('TEMP_SENSOR', {}).get('A_LABEL', 'Sensor A')
            a_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('A_I2C_ADDRESS', '0x77')
            a_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('A_PIN_1', 'notdefined')
            a_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('A_PIN_2', 'notdefined')

            try:
                self.sensors[0] = a_sensor(
                    self.config,
                    a_sensor_label,
                    self.night_v,
                    pin_1_name=a_sensor_pin_1_name,
                    pin_2_name=a_sensor_pin_2_name,
                    i2c_address=a_sensor_i2c_address,
                )
            except (OSError, ValueError, SensorException) as e:
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
            b_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('B_PIN_2', 'notdefined')

            try:
                self.sensors[1] = b_sensor(
                    self.config,
                    b_sensor_label,
                    self.night_v,
                    pin_1_name=b_sensor_pin_1_name,
                    pin_2_name=b_sensor_pin_2_name,
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

        sensor_1_key = self.config.get('TEMP_SENSOR', {}).get('B_USER_VAR_SLOT', 'sensor_user_20')
        self.sensors[1].slot = constants.SENSOR_INDEX_MAP[sensor_1_key]


        ### Sensor C
        c_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('C_CLASSNAME')
        if c_sensor_classname:
            c_sensor = getattr(indi_allsky_sensors, c_sensor_classname)

            c_sensor_label = self.config.get('TEMP_SENSOR', {}).get('C_LABEL', 'Sensor C')
            c_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('C_I2C_ADDRESS', '0x40')
            c_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('C_PIN_1', 'notdefined')
            c_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('C_PIN_2', 'notdefined')

            try:
                self.sensors[2] = c_sensor(
                    self.config,
                    c_sensor_label,
                    self.night_v,
                    pin_1_name=c_sensor_pin_1_name,
                    pin_2_name=c_sensor_pin_2_name,
                    i2c_address=c_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[2] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor C',
                    self.night_v,
                )
        else:
            self.sensors[2] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor C',
                self.night_v,
            )

        sensor_2_key = self.config.get('TEMP_SENSOR', {}).get('C_USER_VAR_SLOT', 'sensor_user_30')
        self.sensors[2].slot = constants.SENSOR_INDEX_MAP[sensor_2_key]


        ### Sensor D
        d_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('D_CLASSNAME')
        if d_sensor_classname:
            d_sensor = getattr(indi_allsky_sensors, d_sensor_classname)

            d_sensor_label = self.config.get('TEMP_SENSOR', {}).get('D_LABEL', 'Sensor D')
            d_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('D_I2C_ADDRESS', '0x50')
            d_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('D_PIN_1', 'notdefined')
            d_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('D_PIN_2', 'notdefined')

            try:
                self.sensors[3] = d_sensor(
                    self.config,
                    d_sensor_label,
                    self.night_v,
                    pin_1_name=d_sensor_pin_1_name,
                    pin_2_name=d_sensor_pin_2_name,
                    i2c_address=d_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[3] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor D',
                    self.night_v,
                )
        else:
            self.sensors[3] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor D',
                self.night_v,
            )

        sensor_3_key = self.config.get('TEMP_SENSOR', {}).get('D_USER_VAR_SLOT', 'sensor_user_40')
        self.sensors[3].slot = constants.SENSOR_INDEX_MAP[sensor_3_key]


        ### Sensor E
        e_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('E_CLASSNAME')
        if e_sensor_classname:
            e_sensor = getattr(indi_allsky_sensors, e_sensor_classname)

            e_sensor_label = self.config.get('TEMP_SENSOR', {}).get('E_LABEL', 'Sensor E')
            e_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('E_I2C_ADDRESS', '0x51')
            e_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('E_PIN_1', 'notdefined')
            e_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('E_PIN_2', 'notdefined')

            try:
                self.sensors[4] = e_sensor(
                    self.config,
                    e_sensor_label,
                    self.night_v,
                    pin_1_name=e_sensor_pin_1_name,
                    pin_2_name=e_sensor_pin_2_name,
                    i2c_address=e_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[4] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor E',
                    self.night_v,
                )
        else:
            self.sensors[4] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor E',
                self.night_v,
            )

        sensor_4_key = self.config.get('TEMP_SENSOR', {}).get('E_USER_VAR_SLOT', 'sensor_user_50')
        self.sensors[4].slot = constants.SENSOR_INDEX_MAP[sensor_4_key]


        ### Sensor F
        f_sensor_classname = self.config.get('TEMP_SENSOR', {}).get('F_CLASSNAME')
        if f_sensor_classname:
            f_sensor = getattr(indi_allsky_sensors, f_sensor_classname)

            f_sensor_label = self.config.get('TEMP_SENSOR', {}).get('F_LABEL', 'Sensor F')
            f_sensor_i2c_address = self.config.get('TEMP_SENSOR', {}).get('F_I2C_ADDRESS', '0x52')
            f_sensor_pin_1_name = self.config.get('TEMP_SENSOR', {}).get('F_PIN_1', 'notdefined')
            f_sensor_pin_2_name = self.config.get('TEMP_SENSOR', {}).get('F_PIN_2', 'notdefined')

            try:
                self.sensors[5] = f_sensor(
                    self.config,
                    f_sensor_label,
                    self.night_v,
                    pin_1_name=f_sensor_pin_1_name,
                    pin_2_name=f_sensor_pin_2_name,
                    i2c_address=f_sensor_i2c_address,
                )
            except (OSError, ValueError) as e:
                logger.error('Error initializing sensor: %s', str(e))
                self.sensors[5] = indi_allsky_sensors.sensor_simulator(
                    self.config,
                    'Sensor F',
                    self.night_v,
                )
        else:
            self.sensors[5] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor F',
                self.night_v,
            )

        sensor_5_key = self.config.get('TEMP_SENSOR', {}).get('F_USER_VAR_SLOT', 'sensor_user_55')
        self.sensors[5].slot = constants.SENSOR_INDEX_MAP[sensor_5_key]


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
