#!/usr/bin/env python3
######################################################
# This script initializes and validates external     #
# temperature/light/etc sensors are functional       #
######################################################

import sys
from pathlib import Path
import argparse
import math
import ephem
import time
from datetime import datetime
from datetime import timezone
#from pprint import pformat
import logging

from multiprocessing import Value
from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.devices import sensors as indi_allsky_sensors
from indi_allsky.devices.exceptions import SensorException
from indi_allsky.devices.exceptions import SensorReadException


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class TestSensors(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config

        self.night_v = Value('i', -1)  # bogus initial value
        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])

        self.sensors = [None, None, None, None, None, None]

        self._count = 1
        self._interval = 5


    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, new_count):
        self._count = int(new_count)


    @property
    def interval(self):
        return self._interval

    @interval.setter
    def interval(self, new_interval):
        self._interval = int(new_interval)


    def main(self):
        obs = ephem.Observer()
        obs.lon = math.radians(self.config['LOCATION_LONGITUDE'])
        obs.lat = math.radians(self.config['LOCATION_LATITUDE'])
        obs.elevation = self.config.get('LOCATION_ELEVATION', 300)

        # disable atmospheric refraction calcs
        obs.pressure = 0

        sun = ephem.Sun()

        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        obs.date = utcnow
        sun.compute(obs)

        with self.night_v.get_lock():
            self.night_v.value = int(sun.alt < self.night_sun_radians)


        self.init_sensors()


        # update sensor readings
        for _ in range(self.count):

            if self.count > 1:
                time.sleep(self.interval)


            for i, sensor in enumerate(self.sensors):

                if isinstance(sensor, type(None)):
                    continue

                try:
                    sensor_data = sensor.update()

                    logger.info('Sensor %d: %s', i, str(sensor_data))
                except SensorReadException as e:
                    logger.error('SensorReadException: {0:s}'.format(str(e)))
                except OSError as e:
                    logger.error('Sensor OSError: {0:s}'.format(str(e)))
                except IOError as e:
                    logger.error('Sensor IOError: {0:s}'.format(str(e)))


        # deinit sensors
        for sensor in self.sensors:
            sensor.deinit()


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
            logger.warning('No sensor A - Initializing sensor simulator')
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
            logger.warning('No sensor B - Initializing sensor simulator')
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
            logger.warning('No sensor C - Initializing sensor simulator')
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
            logger.warning('No sensor D - Initializing sensor simulator')
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
            logger.warning('No sensor E - Initializing sensor simulator')
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
            logger.warning('No sensor F - Initializing sensor simulator')
            self.sensors[5] = indi_allsky_sensors.sensor_simulator(
                self.config,
                'Sensor F',
                self.night_v,
            )

        sensor_5_key = self.config.get('TEMP_SENSOR', {}).get('F_USER_VAR_SLOT', 'sensor_user_55')
        self.sensors[5].slot = constants.SENSOR_INDEX_MAP[sensor_5_key]


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--count',
        '-c',
        help='number of sensor reads to perform (default: 1)',
        type=int,
        default=1
    )
    argparser.add_argument(
        '--interval',
        '-i',
        help='interval between sensor reads (default: 5)',
        type=int,
        default=5
    )


    args = argparser.parse_args()


    ts = TestSensors()
    ts.count = args.count
    ts.interval = args.interval

    ts.main()

