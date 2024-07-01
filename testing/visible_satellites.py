#!/usr/bin/env python3

#import sys
import io
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
import argparse
import socket
import ssl
import requests
import logging
import math
import ephem
from pprint import pformat  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging


class SatelliteTrack(object):
    sats_tle_url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle'  # 100 brightest
    sats_temp_file = '/tmp/sats_27272897.txt'


    def __init__(self):
        self.sats_tle_data = None

        self._latitude = None
        self._longitude = None
        self._time = None


    @property
    def latitude(self):
        return self._latitude

    @latitude.setter
    def latitude(self, new_latitude):
        self._latitude = float(new_latitude)


    @property
    def longitude(self):
        return self._longitude

    @longitude.setter
    def longitude(self, new_longitude):
        self._longitude = float(new_longitude)


    @property
    def time(self):
        return self._time

    @time.setter
    def time(self, new_time):
        new_time_str = str(new_time)

        if new_time_str == 'utcnow':
            self._time = datetime.now(tz=timezone.utc)
            return

        self._time = datetime.strptime(new_time_str, '%Y%m%d%H%M%S')


    def main(self):
        sats_temp_file_p = Path(self.sats_temp_file)


        now = datetime.now()
        now_minus_24h = now - timedelta(hours=24)


        # allow data to be reused
        if not self.sats_tle_data:
            try:
                if not sats_temp_file_p.exists():
                    self.sats_tle_data = self.download_tle(self.sats_tle_url, sats_temp_file_p)
                elif sats_temp_file_p.stat().st_mtime < now_minus_24h.timestamp():
                    logger.warning('Data is older than 24 hours')
                    self.sats_tle_data = self.download_tle(self.sats_tle_url, sats_temp_file_p)
                else:
                    self.sats_tle_data = self.load_tle(sats_temp_file_p)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.sats_tle_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.sats_tle_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.sats_tle_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.sats_tle_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.sats_tle_data = None


        sats_list = list()
        if self.sats_tle_data:
            logger.warning('Latitude:  %0.1f', self.latitude)
            logger.warning('Longitude: %0.1f', self.longitude)
            logger.warning('Time:      %s (utc)', self.time)

            obs = ephem.Observer()
            obs.lat = math.radians(self.latitude)
            obs.long = math.radians(self.longitude)
            obs.elevation = 300

            # disable atmospheric refraction calcs
            obs.pressure = 0


            tle_iter = iter(self.sats_tle_data)
            while True:
                try:
                    title = next(tle_iter).strip()
                except StopIteration:
                    break


                #if line.startswith('#'):
                #    continue
                #elif line == "":
                #    continue


                try:
                    line1 = next(tle_iter).strip()
                    line2 = next(tle_iter).strip()
                except StopIteration:
                    logger.error('Error parsing TLE data')
                    break


                try:
                    sat = ephem.readtle(title, line1, line2)
                except ValueError as e:
                    logger.error('Satellite TLE data error: %s', str(e))
                    raise


                sats_list.append({
                    'title' : title,
                    'tle'   : sat,
                })

            #logger.info('%s', dir(iss))


            obs.date = self.time
            #obs.date = self.time + timedelta(hours=6)  # testing


            for sat in sats_list:
                sat['tle'].compute(obs)

                sat_alt = math.degrees(sat['tle'].alt)

                if sat_alt < 0:
                    #logger.info('%s: below horizon', sat['title'])
                    continue


                if sat['tle'].eclipsed:
                    continue


                logger.info('%s: altitude %0.1f, azimuth %0.1f, elevation %dkm', sat['title'], math.degrees(sat['tle'].alt), math.degrees(sat['tle'].az), int(sat['tle'].elevation / 1000))


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
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--latitude',
        '--lat',
        help='latitude',
        type=float,
        required=True,
    )
    argparser.add_argument(
        '--longitude',
        '--long',
        help='longitude',
        type=float,
        required=True,
    )
    argparser.add_argument(
        '--time',
        help='UTC time yyyymmddHHMMSS (default: utcnow)',
        default='utcnow',
        type=str,
    )


    args = argparser.parse_args()


    s = SatelliteTrack()
    s.latitude = args.latitude
    s.longitude = args.longitude
    s.time = args.time
    s.main()

