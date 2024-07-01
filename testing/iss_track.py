#!/usr/bin/env python3

#import sys
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
import time
import ephem
from pprint import pformat  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging


CITY = 'Atlanta'


class IssTrack(object):
    iss_tle_url = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE'
    iss_temp_file = '/tmp/iss_27272897.txt'


    def __init__(self):
        self.iss_tle_data = None


    def main(self):
        iss_temp_file_p = Path(self.iss_temp_file)


        now = datetime.now()
        now_minus_24h = now - timedelta(hours=24)


        # allow data to be reused
        if not self.iss_tle_data:
            try:
                if not iss_temp_file_p.exists():
                    self.iss_tle_data = self.download_tle(self.iss_tle_url, iss_temp_file_p)
                elif iss_temp_file_p.stat().st_mtime < now_minus_24h.timestamp():
                    logger.warning('Data is older than 24 hours')
                    self.iss_tle_data = self.download_tle(self.iss_tle_url, iss_temp_file_p)
                else:
                    self.iss_tle_data = self.load_tle(iss_temp_file_p)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.hms_kml_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.iss_tle_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.iss_tle_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.iss_tle_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.iss_tle_data = None



        if self.iss_tle_data:
            obs = ephem.city(CITY)

            #obs = ephem.Observer()
            #obs.lat = math.radians(89)
            #obs.long = math.radians(0)
            #obs.elevation = 300

            # disable atmospheric refraction calcs
            obs.pressure = 0

            try:
                iss = ephem.readtle(*self.iss_tle_data)
            except ValueError as e:
                logger.error('Satellite TLE data error: %s', str(e))
                raise

            #logger.info('%s', dir(iss))


            while True:
                utcnow = datetime.now(tz=timezone.utc)

                obs.date = utcnow
                #obs.date = utcnow + timedelta(hours=6)  # testing

                iss.compute(obs)

                try:
                    iss_next_pass = obs.next_pass(iss)
                except ValueError as e:
                    logger.error('Next pass error: %s', str(e))
                    raise

                logger.info('iss: altitude %4.1f, azimuth %5.1f', math.degrees(iss.alt), math.degrees(iss.az))
                logger.info(' next rise: {0:%Y-%m-%d %H:%M:%S} ({1:0.1f}h), max: {2:%Y-%m-%d %H:%M:%S}, set: {3:%Y-%m-%d %H:%M:%S} - duration {4:d}s - elev {5:0.1f}km'.format(
                    ephem.localtime(iss_next_pass[0]),
                    (iss_next_pass[0].datetime() - utcnow.replace(tzinfo=None)).total_seconds() / 3600,
                    ephem.localtime(iss_next_pass[2]),
                    ephem.localtime(iss_next_pass[4]),
                    (ephem.localtime(iss_next_pass[4]) - ephem.localtime(iss_next_pass[0])).seconds,
                    iss.elevation / 1000,
                ))

                time.sleep(5.0)



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
    a = IssTrack()
    a.main()


