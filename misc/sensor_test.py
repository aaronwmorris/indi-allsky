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

from multiprocessing import Array
from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
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

        # These shared values are to indicate when the camera is in night/moon modes
        self.night_av = Array('i', [
            -1,  # night, bogus initial value
            0,  # moonmode, not used
        ])


        self.astro_av = Array('f', [
            0.0,  # sun alt
            0.0,  # moon alt
            0.0,  # moon percent
        ])


        self.night_sun_radians = math.radians(self.config['NIGHT_SUN_ALT_DEG'])

        self.sensors = []

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
        moon = ephem.Moon()

        utcnow = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        obs.date = utcnow

        sun.compute(obs)
        moon.compute(obs)


        with self.night_av.get_lock():
            self.night_av[constants.NIGHT_NIGHT] = int(sun.alt < self.night_sun_radians)


        with self.astro_av.get_lock():
            self.astro_av[constants.ASTRO_SUN_ALT] = float(math.degrees(sun.alt))
            self.astro_av[constants.ASTRO_MOON_ALT] = float(math.degrees(moon.alt))
            self.astro_av[constants.ASTRO_MOON_PHASE] = float(moon.moon_phase * 100.0)


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
        from indi_allsky.sensor_slots import initialize_sensors

        self.sensors = initialize_sensors(self.config, self.night_av, self.astro_av)


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
