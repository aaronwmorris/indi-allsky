import time
#from datetime import datetime
#from datetime import timezone
import socket
import re
import ssl
#import math
import json
import urllib3.exceptions
import requests
import numpy
import logging

from .flask import db
from .flask.miscDb import miscDb


logger = logging.getLogger('indi_allsky')


class IndiAllskyAuroraUpdate(object):

    ovation_json_url = 'https://services.swpc.noaa.gov/json/ovation_aurora_latest.json'
    kpindex_json_url = 'https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json'
    solar_wind_mag_json_url = 'https://services.swpc.noaa.gov/products/solar-wind/mag-5-minute.json'
    solar_wind_plasma_json_url = 'https://services.swpc.noaa.gov/products/solar-wind/plasma-5-minute.json'
    hemi_power_url = 'https://services.swpc.noaa.gov/text/aurora-nowcast-hemi-power.txt'


    def __init__(self, config):
        self.config = config

        self._miscDb = miscDb(self.config)


        ### caching the data allows multiple cameras to be updated in the same run
        self.ovation_json_data = None
        self.kpindex_json_data = None
        self.solar_wind_mag_json_data = None
        self.solar_wind_plasma_json_data = None
        self.hemi_power_data = None


    def update(self, camera):
        latitude = camera.latitude
        longitude = camera.longitude


        if camera.data:
            camera_data = dict(camera.data)
        else:
            camera_data = dict()


        camera_update = False

        try:
            self.update_ovation(camera_data, latitude, longitude)
            camera_update = True
        except AuroraDataUpdateFailure:
            pass


        try:
            self.update_kpindex(camera_data)
            camera_update = True
        except AuroraDataUpdateFailure:
            pass


        try:
            self.update_solar_wind_mag_data(camera_data)
            camera_update = True
        except AuroraDataUpdateFailure:
            pass


        try:
            self.update_solar_wind_plasma_data(camera_data)
            camera_update = True
        except AuroraDataUpdateFailure:
            pass


        try:
            self.update_hemi_power_data(camera_data)
            camera_update = True
        except AuroraDataUpdateFailure:
            pass


        if camera_update:
            camera_data['AURORA_DATA_TS'] = int(time.time())
            camera.data = camera_data
            db.session.commit()


    def update_ovation(self, camera_data, latitude, longitude):
        if not self.ovation_json_data:
            try:
                self.ovation_json_data = self.download_json(self.ovation_json_url)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ReadTimeout as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e


        max_ovation, avg_ovation = self.processOvationLocationData(self.ovation_json_data, latitude, longitude)
        logger.info('Max Ovation: %d', max_ovation)
        logger.info('Avg Ovation: %0.2f', avg_ovation)

        camera_data['OVATION_MAX'] = max_ovation


    def processOvationLocationData(self, json_data, latitude, longitude):
        # this will check a 5 degree by 5 degree grid and aggregate all of the ovation scores

        logger.warning('Looking up data for %0.1f, %0.1f', latitude, longitude)

        if longitude < 0:
            longitude = 360 + longitude  # logitude is negative


        # 1 degree is ~69 miles (equator), 7 degrees should be just under 500 miles

        # this will not work exactly right at the north and south poles above 80 degrees latitude
        lat_int = round(latitude)
        lat_list = [lat_int + x for x in range(-7, 8)]

        # longitude gets more compressed the further north/south from equator
        long_int = round(longitude)
        long_list = [long_int + x for x in range(-9, 10)]  # expand a bit


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


    def update_kpindex(self, camera_data):
        if not self.kpindex_json_data:
            try:
                self.kpindex_json_data = self.download_json(self.kpindex_json_url)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e


        kpindex, kpindex_poly = self.processKpindexPoly(self.kpindex_json_data)
        logger.info('kpindex: %0.2f', kpindex)
        logger.info('Data: x = %0.2f, b = %0.2f', kpindex_poly.coef[0], kpindex_poly.coef[1])

        camera_data['KPINDEX_CURRENT'] = round(kpindex, 2)
        camera_data['KPINDEX_COEF'] = round(kpindex_poly.coef[0], 2)


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

        # use linear regression to calculate general trend
        p_fitted = numpy.polynomial.Polynomial.fit(x, y, deg=1)

        return kp_last, p_fitted.convert()


    def update_solar_wind_mag_data(self, camera_data):
        if not self.solar_wind_mag_json_data:
            try:
                self.solar_wind_mag_json_data = self.download_json(self.solar_wind_mag_json_url)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e


        try:
            Bt, gsm_Bz = self.processSolarWindMagData(self.solar_wind_mag_json_data)
        except ValueError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except KeyError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except IndexError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e


        logger.info('Aurora - Bt: %0.2f, GSM Bz: %0.2f', gsm_Bz, Bt)

        camera_data['AURORA_MAG_BT'] = round(Bt, 2)
        camera_data['AURORA_MAG_GSM_BZ'] = round(gsm_Bz, 2)


    def processSolarWindMagData(self, json_data):
        data_index = json_data[0]

        last_Bt = float(json_data[-1][data_index.index('bt')])
        last_gsm_Bz = float(json_data[-1][data_index.index('bz_gsm')])


        return last_Bt, last_gsm_Bz


    def update_solar_wind_plasma_data(self, camera_data):
        if not self.solar_wind_plasma_json_data:
            try:
                self.solar_wind_plasma_json_data = self.download_json(self.solar_wind_plasma_json_url)
            except json.JSONDecodeError as e:
                logger.error('JSON parse error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e


        try:
            density, speed = self.processSolarWindPlasmaData(self.solar_wind_mag_json_data)
        except ValueError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except KeyError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except IndexError as e:
            logger.error('Solar Wind processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e


        logger.info('Solar Wind - Density: %0.2f, Speed: %0.2f', density, speed)

        camera_data['AURORA_PLASMA_DENSITY'] = round(density, 2)
        camera_data['AURORA_PLASMA_SPEED'] = round(speed, 2)


    def processSolarWindPlasmaData(self, json_data):
        data_index = json_data[0]

        last_density = float(json_data[-1][data_index.index('density')])
        last_speed = float(json_data[-1][data_index.index('speed')])


        return last_density, last_speed


    def update_hemi_power_data(self, camera_data):
        if not self.hemi_power_data:
            try:
                self.hemi_power_data = self.download_txt(self.hemi_power_url)
            except socket.gaierror as e:
                logger.error('Name resolution error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except socket.timeout as e:
                logger.error('Timeout error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectTimeout as e:
                logger.error('Connection timeout: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.ConnectionError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except urllib3.exceptions.ReadTimeoutError as e:
                logger.error('Connection error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except ssl.SSLCertVerificationError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e
            except requests.exceptions.SSLError as e:
                logger.error('Certificate error: %s', str(e))
                raise AuroraDataUpdateFailure from e


        try:
            n_hemi_gw, s_hemi_gw = self.processHemiPowerData(self.hemi_power_data)
        except IndexError as e:
            logger.error('Hemispheric power processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except KeyError as e:
            logger.error('Hemispheric power processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e
        except ValueError as e:
            logger.error('Hemispheric power processing error: %s', str(e))
            raise AuroraDataUpdateFailure from e


        logger.info('Hemispheric Power - N: %d GW, S: %d GW', n_hemi_gw, s_hemi_gw)

        camera_data['AURORA_N_HEMI_GW'] = n_hemi_gw
        camera_data['AURORA_S_HEMI_GW'] = s_hemi_gw


    def processHemiPowerData(self, text_data):
        re_power = re.compile(r'^(?P<obs_str>\S+)\s+(?P<forecast_str>\S+)\s+(?P<n_gw>\d+)\s+(?P<s_gw>\d+)$')

        power_data = list()
        for line in text_data.splitlines():
            if line.startswith('#'):
                continue

            m = re.search(re_power, line)
            if not m:
                #logger.error('Hemispheric power regex parse error')
                continue

            d = {
                ### do not need timestamps at this time
                #'obs' : datetime.strptime(m.group('obs_str'), '%Y-%m-%d_%H:%M').replace(tzinfo=timezone.utc),
                #'forecast' : datetime.strptime(m.group('forecast_str'), '%Y-%m-%d_%H:%M').replace(tzinfo=timezone.utc),
                'n_gw' : int(m.group('n_gw')),
                's_gw' : int(m.group('s_gw')),
            }

            power_data.append(d)


        # use last value
        last_n_hemi_gw = power_data[-1]['n_gw']
        last_s_hemi_gw = power_data[-1]['s_gw']

        return last_n_hemi_gw, last_s_hemi_gw


    def download_json(self, url):
        logger.warning('Downloading %s', url)

        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        json_data = json.loads(r.text)
        #logger.warning('Response: %s', json_data)

        return json_data


    def download_txt(self, url):
        logger.warning('Downloading %s', url)

        r = requests.get(url, allow_redirects=True, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return None

        data = r.text
        #logger.warning('Response: %s', data)

        return data


class AuroraDataUpdateFailure(Exception):
    pass

