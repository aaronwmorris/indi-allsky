#!/usr/bin/env python3

import sys
import io
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import socket
import ssl
import requests
import logging
import math
#import time
import ephem
from pprint import pformat  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging


LATITUDE = 61.0
LONGITUDE = 24.0


class SatelliteShakedown(object):
    ### iss
    #sat_tle_url = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE'
    #tle_temp_file = '/tmp/iss_25544.txt'

    ### hubble
    #sat_tle_url = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=20580&FORMAT=TLE'
    #tle_temp_file = '/tmp/hst_20580.txt'


    ### tiangong
    sat_tle_url = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=48274&FORMAT=TLE'
    tle_temp_file = '/tmp/tiangong_48274.txt'


    def __init__(self):
        self.tle_data = None


    def main(self):
        tle_temp_file_p = Path(self.tle_temp_file)


        now = datetime.now()
        now_minus_24h = now - timedelta(hours=24)


        # allow data to be reused
        if not self.tle_data:
            try:
                if not tle_temp_file_p.exists():
                    self.tle_data = self.download_tle(self.sat_tle_url, tle_temp_file_p)
                elif tle_temp_file_p.stat().st_mtime < now_minus_24h.timestamp():
                    logger.warning('Data is older than 24 hours')
                    self.tle_data = self.download_tle(self.sat_tle_url, tle_temp_file_p)
                else:
                    self.tle_data = self.load_tle(tle_temp_file_p)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.tle_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.tle_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.tle_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.tle_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.tle_data = None


        if isinstance(self.tle_data, type(None)):
            logger.error('TLE data is not populated')
            sys.exit(1)


        if self.tle_data:
            obs = ephem.Observer()
            obs.lat = math.radians(LATITUDE)
            obs.long = math.radians(LONGITUDE)
            obs.elevation = 300

            # disable atmospheric refraction calcs
            obs.pressure = 0

            try:
                sat = ephem.readtle(*self.tle_data)
            except ValueError as e:
                logger.error('Satellite TLE data error: %s', str(e))
                sys.exit(1)
            except TypeError as e:
                logger.error('Satellite TLE data error: %s', str(e))
                sys.exit(1)

            #logger.info('%s', dir(sat))


            utcnow = datetime.now(tz=timezone.utc)
            #utcnow = datetime.fromtimestamp(1234567890, tz=timezone.utc)  # testing

            for x in range(1440):
                if x % 60 == 0:
                    logger.info('Minute: %+d', x)

                utcnow_delta = utcnow + timedelta(minutes=x)

                obs.date = utcnow_delta

                sat.compute(obs)

                try:
                    sat_next_pass = obs.next_pass(sat)
                #except ValueError as e:
                    #logger.error('Next pass error: %s', str(e))
                    #raise
                except ValueError:
                    continue


                try:
                    assert len(sat_next_pass) == 6
                except AssertionError:
                    logger.error('Next pass did not return 6 values')
                    sys.exit(1)


                try:
                    sat_next_pass[0].datetime()
                except AttributeError:
                    logger.info('Attribute Error on index 0 - Timestamp: %d', int(utcnow_delta.timestamp()))
                    sys.exit(1)


                #try:
                #    sat_next_pass[1].datetime()
                #except AttributeError:
                #    logger.info('Attribute Error on index 1 - Timestamp: %d', int(utcnow_delta.timestamp()))
                #    sys.exit(1)


                #try:
                #    sat_next_pass[2].datetime()
                #except AttributeError:
                #    logger.info('Attribute Error on index 2 - Timestamp: %d', int(utcnow_delta.timestamp()))
                #    sys.exit(1)


                #try:
                #    sat_next_pass[3].datetime()
                #except AttributeError:
                #    logger.info('Attribute Error on index 3 - Timestamp: %d', int(utcnow_delta.timestamp()))
                #    sys.exit(1)


                #try:
                #    sat_next_pass[4].datetime()
                #except AttributeError:
                #    logger.info('Attribute Error on index 4 - Timestamp: %d', int(utcnow_delta.timestamp()))
                #    sys.exit(1)


                #try:
                #    sat_next_pass[5].datetime()
                #except AttributeError:
                #    logger.info('Attribute Error on index 5 - Timestamp: %d', int(utcnow_delta.timestamp()))
                #    sys.exit(1)


                #logger.info('Satellite: altitude %4.1f, azimuth %5.1f', math.degrees(sat.alt), math.degrees(sat.az))
                #logger.info(' next rise: {0:%Y-%m-%d %H:%M:%S} ({1:0.1f}h), max: {2:%Y-%m-%d %H:%M:%S}, set: {3:%Y-%m-%d %H:%M:%S} - duration {4:d}s - elev {5:0.1f}km'.format(
                #    ephem.localtime(sat_next_pass[0]),
                #    (sat_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600,
                #    ephem.localtime(sat_next_pass[2]),
                #    ephem.localtime(sat_next_pass[4]),
                #    (ephem.localtime(sat_next_pass[4]) - ephem.localtime(sat_next_pass[0])).seconds,
                #    sat.elevation / 1000,
                #))


    def download_tle(self, url, tmpfile):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=15.0)

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        with io.open(tmpfile, 'w') as f_tle:
            f_tle.write(r.text)


        return r.text.splitlines()


    def load_tle(self, tmpfile):
        logger.warning('Loading tle data: %s', tmpfile)
        with io.open(tmpfile, 'r') as f_tle:
            tle_data = f_tle.readlines()


        return tle_data


if __name__ == "__main__":
    a = SatelliteShakedown()
    a.main()


