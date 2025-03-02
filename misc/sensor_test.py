#!/usr/bin/env python3

import sys
import math
from datetime import datetime
from datetime import timezone
import ephem
import logging
#import time
from pathlib import Path
#from pprint import pformat

from multiprocessing import Value

from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.devices import sensors as indi_allsky_sensors
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

        self.sensors = [None, None, None]


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
            logger.warning('No sensor B - Initializing sensor simulator')
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

        sensor_2_key = self.config.get('TEMP_SENSOR', {}).get('C_USER_VAR_SLOT', 'sensor_user_20')
        self.sensors[2].slot = constants.SENSOR_INDEX_MAP[sensor_2_key]


if __name__ == "__main__":
    ts = TestSensors()
    ts.main()

