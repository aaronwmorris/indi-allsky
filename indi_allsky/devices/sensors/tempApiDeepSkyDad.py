import socket
import time
import json
import ssl
import requests
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempApiDeepSkyDad(SensorBase):

    ### {
    ###     "fv": 0,
    ###     "fw": "0.0.8",
    ###     "ht": 30.08,
    ###     "hv": 0,
    ###     "oc": 17.71,
    ###     "oe": 1,
    ###     "rc": 247.44,
    ###     "sh": 34.47,
    ###     "st": 28.37
    ### }


    URL = 'http://localhost:8080/ace_api/overlays'


    METADATA = {
        'name' : 'DeepSkyDad API',
        'description' : 'DeepSkyDad API Sensor',
        'count' : 8,
        'labels' : (
            'fv',
            'ht',
            'hv',
            'oc',
            'oe',
            'rc',
            'sh',
            'st',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempApiDeepSkyDad, self).__init__(*args, **kwargs)

        logger.warning('Initializing [%s] DeepSkyDad API Sensor', self.name)


        self.data = {
            'data' : tuple(),
        }

        self.next_run = time.time()  # run immediately
        self.next_run_offset = 60  # one minute


    def update(self):
        now = time.time()
        if now < self.next_run:
            # return cached data
            return self.data


        self.next_run = now + self.next_run_offset



        try:
            r = requests.get(self.url, verify=False, timeout=(5.0, 10.0))
        except socket.gaierror as e:
            raise SensorReadException(str(e)) from e
        except socket.timeout as e:
            raise SensorReadException(str(e)) from e
        except requests.exceptions.ConnectTimeout as e:
            raise SensorReadException(str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise SensorReadException(str(e)) from e
        except requests.exceptions.ReadTimeout as e:
            raise SensorReadException(str(e)) from e
        except ssl.SSLCertVerificationError as e:
            raise SensorReadException(str(e)) from e
        except requests.exceptions.SSLError as e:
            raise SensorReadException(str(e)) from e



        if r.status_code >= 400:
            raise SensorReadException('DeepSkyDad API returned {0:d}'.format(r.status_code))


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            raise SensorReadException(str(e)) from e


        fv = r_data.get("fv", 0)
        ht = r_data.get("ht", 0.0)
        hv = r_data.get("hv", 0)
        oc = r_data.get("oc", 0.0)
        oe = r_data.get("oe", 0)
        rc = r_data.get("rc", 0.0)
        sh = r_data.get("sh", 0.0)
        st = r_data.get("st", 0.0)


        logger.info('[%s] DeepSkyDad API - ', self.name)


        self.data = {
            'data' : (
                fv,
                ht,
                hv,
                oc,
                oe,
                rc,
                sh,
                st,
            ),
        }

        return self.data

