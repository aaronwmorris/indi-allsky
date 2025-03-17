#!/usr/bin/env python3


import io
import socket
import ssl
import math
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import json
import requests
import numpy
import logging


#requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logging.basicConfig(level=logging.INFO)
logger = logging


### NYC
#LATITUDE  = 40
#LONGITUDE = -74

### London
#LATITUDE  = 51
#LONGITUDE = -1

### Helsinki
LATITUDE  = 60
LONGITUDE = 25



class AuroraTest(object):
    ovation_json_url = 'https://services.swpc.noaa.gov/json/ovation_aurora_latest.json'
    ovation_temp_json = '/tmp/ovation_aurora_latest_8275672.json'

    kpindex_json_url = 'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'
    kpindex_temp_json = '/tmp/noaa-planetary-k-index_3418272.json'



    def __init__(self):
        self.ovation_json_data = None
        self.kpindex_json_data = None


    def main(self):
        ovation_json_p = Path(self.ovation_temp_json)
        kpindex_json_p = Path(self.kpindex_temp_json)


        now = datetime.now()
        now_minus_3h = now - timedelta(hours=3)


        # allow data to be reused
        if not self.ovation_json_data:
            try:
                if not ovation_json_p.exists():
                    self.ovation_json_data = self.download_json(self.ovation_json_url, ovation_json_p)
                elif ovation_json_p.stat().st_mtime < now_minus_3h.timestamp():
                    logger.warning('ovation json is older than 3 hours')
                    self.ovation_json_data = self.download_json(self.ovation_json_url, ovation_json_p)
                else:
                    self.ovation_json_data = self.load_json(ovation_json_p)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                self.ovation_json_data = None
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.ovation_json_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.ovation_json_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.ovation_json_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.ovation_json_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.ovation_json_data = None


        # allow data to be reused
        if not self.kpindex_json_data:
            try:
                if not kpindex_json_p.exists():
                    self.kpindex_json_data = self.download_json(self.kpindex_json_url, kpindex_json_p)
                elif kpindex_json_p.stat().st_mtime < now_minus_3h.timestamp():
                    logger.warning('kpindex json is older than 3 hours')
                    self.kpindex_json_data = self.download_json(self.kpindex_json_url, kpindex_json_p)
                else:
                    self.kpindex_json_data = self.load_json(kpindex_json_p)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                self.kpindex_json_data = None
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                self.kpindex_json_data = None
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                self.kpindex_json_data = None
            except requests.exceptions.ReadTimeout as e:
                logger.error('Timeout error: %s', str(e))
                self.kpindex_json_data = None
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                self.kpindex_json_data = None
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                self.kpindex_json_data = None



        if self.ovation_json_data:
            max_ovation, avg_ovation = self.processOvationLocationData(self.ovation_json_data, LATITUDE, LONGITUDE)
            logger.info('Max Ovation: %d', max_ovation)
            logger.info('Avg Ovation: %0.2f', avg_ovation)


        if self.kpindex_json_data:
            kpindex, kpindex_poly = self.processKpindexPoly(self.kpindex_json_data)
            logger.info('kpindex: %0.2f', kpindex)
            logger.info('Data: x = %0.2f, b = %0.2f', kpindex_poly.coef[0], kpindex_poly.coef[1])



    def download_json(self, url, tmpfile):
        logger.warning('Downloading %s', url)
        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        json_data = json.loads(r.text)

        with io.open(tmpfile, 'w') as f_json:
            f_json.write(json.dumps(json_data))


        return json_data


    def load_json(self, tmpfile):
        logger.warning('Loading json data: %s', tmpfile)
        with io.open(tmpfile, 'r') as f_json:
            json_data = json.loads(f_json.read())


        return json_data


    def processOvationLocationData(self, json_data, latitude, longitude):
        # this will check a 5 degree by 5 degree grid and aggregate all of the ovation scores

        logger.warning('Looking up data for %0.1f, %0.1f', latitude, longitude)

        if longitude < 0:
            longitude = 360 + longitude  # logitude is negative


        # 1 degree is ~69 miles, 7 degrees should be just under 500 miles

        lat_floor = math.floor(latitude)
        # this will not work exactly right at the north and south poles above 80 degrees latitude
        lat_list = [
            lat_floor - 7,
            lat_floor - 6,
            lat_floor - 5,
            lat_floor - 4,
            lat_floor - 3,
            lat_floor - 2,
            lat_floor - 1,
            lat_floor,
            lat_floor + 1,
            lat_floor + 2,
            lat_floor + 3,
            lat_floor + 4,
            lat_floor + 5,
            lat_floor + 6,
            lat_floor + 7,
        ]

        long_floor = math.floor(longitude)
        long_list = [
            long_floor - 7,  # this should cover northern and southern hemispheres
            long_floor - 6,
            long_floor - 5,
            long_floor - 4,
            long_floor - 3,
            long_floor - 2,
            long_floor - 1,
            long_floor,
            long_floor + 1,
            long_floor + 2,
            long_floor + 3,
            long_floor + 4,
            long_floor + 5,
            long_floor + 6,
            long_floor + 7,
        ]


        # fix longitudes that cross 0/360
        for i in long_list:
            if i < 0:
                i = 360 + i  # i is negative
            elif i > 360:
                i = i - 360


        data_list = list()
        for i in json_data['coordinates']:
            #logger.info('%s', i)

            for long_val in long_list:
                for lat_val in lat_list:
                    if i[0] == long_val and i[1] == lat_val:
                        data_list.append(int(i[2]))


        #logger.info('Data: %s', data_list)

        return max(data_list), sum(data_list) / len(data_list)


    def processKpindexPoly(self, json_data):
        kp_last = float(json_data[-1][1])

        json_iter = iter(json_data)
        next(json_iter)  # skip first index

        kp_list = list()
        for k in json_iter:
            try:
                kp_list.append(float(k[1]))
            except ValueError:
                logger.error('Invalid float: %s', str(k[1]))
                continue


        #logger.info('kpindex data: %s', kp_list)

        x = numpy.arange(0, len(kp_list))
        y = numpy.array(kp_list)

        p_fitted = numpy.polynomial.Polynomial.fit(x, y, deg=1)

        return kp_last, p_fitted.convert()


if __name__ == "__main__":
    a = AuroraTest()
    a.main()


