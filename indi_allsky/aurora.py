import time
import socket
import ssl
import math
import json
import requests
import numpy
import logging

from .flask import db
from .flask.miscDb import miscDb


logger = logging.getLogger('indi_allsky')


class IndiAllskyAuroraUpdate(object):

    ovation_json_url = 'https://services.swpc.noaa.gov/json/ovation_aurora_latest.json'
    kindex_json_url = 'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'


    def __init__(self, config):
        self.config = config

        self._miscDb = miscDb(self.config)


    def update(self, camera):
        try:
            ovation_json_data = self.download_json(self.ovation_json_url)
        except json.JSONDecodeError as e:
            logger.error('JSON parse error: %s', str(e))
            ovation_json_data = None
        except socket.gaierror as e:
            logger.error('Name resolution error: %s', str(e))
            ovation_json_data = None
        except socket.timeout as e:
            logger.error('Timeout error: %s', str(e))
            ovation_json_data = None
        except ssl.SSLCertVerificationError as e:
            logger.error('Certificate error: %s', str(e))
            ovation_json_data = None
        except requests.exceptions.SSLError as e:
            logger.error('Certificate error: %s', str(e))
            ovation_json_data = None


        try:
            kindex_json_data = self.download_json(self.kindex_json_url)
        except json.JSONDecodeError as e:
            logger.error('JSON parse error: %s', str(e))
            kindex_json_data = None
        except socket.gaierror as e:
            logger.error('Name resolution error: %s', str(e))
            kindex_json_data = None
        except socket.timeout as e:
            logger.error('Timeout error: %s', str(e))
            kindex_json_data = None
        except ssl.SSLCertVerificationError as e:
            logger.error('Certificate error: %s', str(e))
            kindex_json_data = None
        except requests.exceptions.SSLError as e:
            logger.error('Certificate error: %s', str(e))
            kindex_json_data = None


        latitude = camera.latitude
        longitude = camera.longitude


        if camera.data:
            camera_data = dict(camera.data)
        else:
            camera_data = dict()


        update_camera = False

        if ovation_json_data:
            max_ovation, avg_ovation = self.processOvationLocationData(ovation_json_data, latitude, longitude)
            logger.info('Max Ovation: %d', max_ovation)
            logger.info('Avg Ovation: %0.2f', avg_ovation)

            camera_data['OVATION_MAX'] = max_ovation
            update_camera = True


        if kindex_json_data:
            kindex, kindex_poly = self.processKindexPoly(kindex_json_data)
            logger.info('kindex: %0.2f', kindex)
            logger.info('Data: x = %0.2f, b = %0.2f', kindex_poly.coef[0], kindex_poly.coef[1])

            camera_data['KINDEX_CURRENT'] = round(kindex, 2)
            camera_data['KINDEX_COEF'] = round(kindex_poly.coef[0], 2)
            update_camera = True


        if update_camera:
            camera_data['AURORA_DATA_TS'] = int(time.time())
            camera.data = camera_data
            db.session.commit()


    def download_json(self, url):
        logger.warning('Downloading %s', url)

        r = requests.get(url, allow_redirects=True, verify=True)

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        json_data = json.loads(r.text)
        #logger.warning('Response: %s', json_data)

        return json_data


    def processOvationLocationData(self, json_data, latitude, longitude):
        # this will check a 5 degree by 5 degree grid and aggregate all of the ovation scores

        logger.warning('Looking up data for %0.1f, %0.1f', latitude, longitude)

        if longitude < 0:
            longitude = 360 + longitude  # logitude is negative


        lat_floor = math.floor(latitude)
        # this will not work right at the north and south poles above 85 degrees latitude
        lat_list = [
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
        ]

        long_floor = math.floor(longitude)
        long_list = [
            long_floor - 5,  # this should cover northern and southern hemispheres
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


    def processKindexPoly(self, json_data):
        k_last = float(json_data[-1][1])

        json_iter = iter(json_data)
        next(json_iter)  # skip first index

        k_list = list()
        for k in json_iter:
            try:
                k_list.append(float(k[1]))
            except ValueError:
                logger.error('Invalid float: %s', str(k[1]))
                continue


        #logger.info('kindex data: %s', k_list)

        x = numpy.arange(0, len(k_list))
        y = numpy.array(k_list)

        p_fitted = numpy.polynomial.Polynomial.fit(x, y, deg=1)

        return k_last, p_fitted.convert()


