#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
from pprint import pformat  # noqa: F401
import time
import json
import re
import psutil
import ssl
import paho.mqtt.publish as publish
import logging

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import create_app
from indi_allsky import constants


app = create_app()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class HADiscovery(object):


    discovery_base_topic = 'homeassistant'
    unique_id_base = '001'


    # maps to SensorDeviceClass
    HA_SENSOR_DEVICE_CLASS = {
        constants.SENSOR_TEMPERATURE          : 'TEMPERATURE',
        constants.SENSOR_RELATIVE_HUMIDITY    : 'HUMIDITY',
        constants.SENSOR_ATMOSPHERIC_PRESSURE : 'ATMOSPHERIC_PRESSURE',
        constants.SENSOR_WIND_SPEED           : 'WIND_SPEED',
        constants.SENSOR_PRECIPITATION        : 'PRECIPITATION',
        constants.SENSOR_CONCENTRATION        : None,
        constants.SENSOR_LIGHT_LUX            : 'ILLUMINANCE',
        constants.SENSOR_LIGHT_MISC           : 'ILLUMINANCE',
        constants.SENSOR_FAN_SPEED            : None,
        constants.SENSOR_PERCENTAGE           : None,
        constants.SENSOR_MISC                 : None,
    }


    # https://github.com/home-assistant/core/blob/master/homeassistant/const.py
    HA_UNIT_MAP = {
        constants.SENSOR_TEMPERATURE : {
            'c' : '°C',
            'f' : '°F',
            'k' : 'K',
            'degree'  : '°',
            'degrees' : '°',
        },
        constants.SENSOR_RELATIVE_HUMIDITY : {
            'percent' : '%',
            '%'       : '%',
        },
        constants.SENSOR_ATMOSPHERIC_PRESSURE : {
            'hpa'  : 'hPa',
            'mbar' : 'mbar',
            'inhg' : 'inHg',
            'mmhg' : 'mmHg',
            'psi'  : 'psi',
        },
        constants.SENSOR_WIND_SPEED : {
            'ms'   : 'm/s',
            'kph'  : 'km/h',
            'mph'  : 'mph',
        },
        constants.SENSOR_PRECIPITATION : {
            'in'   : 'in',
            'mm'   : 'mm',
            'cm'   : 'cm',
        },
        constants.SENSOR_CONCENTRATION : {
            'ppm'  : 'ppm',
            'ppb'  : 'ppb',
        },
        constants.SENSOR_PERCENTAGE : {
            'percent' : '%',
            '%'       : '%',
        },
        constants.SENSOR_LIGHT_LUX : {
            'lux'     : 'lx',
        },
        constants.SENSOR_FAN_SPEED : {
            'rpm'     : 'rpm',
        },
    }


    # this structure is from the flask wtforms type (I am too lazy to change it)
    SENSOR_SLOT_choices = [  # mutable
        ('0', 'Camera Temp'),
        ('1', 'Dew Heater Level'),
        ('2', 'Dew Point'),
        ('3', 'Frost Point'),
        ('4', 'Fan Level'),
        ('5', 'Heat Index'),
        ('6', 'Wind Dir Degrees'),
        ('7', 'SQM'),
        ('8', 'Future Use 8'),
        ('9', 'Future Use 9'),
        ('10', 'User Slot 10'),
        ('11', 'User Slot 11'),
        ('12', 'User Slot 12'),
        ('13', 'User Slot 13'),
        ('14', 'User Slot 14'),
        ('15', 'User Slot 15'),
        ('16', 'User Slot 16'),
        ('17', 'User Slot 17'),
        ('18', 'User Slot 18'),
        ('19', 'User Slot 19'),
        ('20', 'User Slot 20'),
        ('21', 'User Slot 21'),
        ('22', 'User Slot 22'),
        ('23', 'User Slot 23'),
        ('24', 'User Slot 24'),
        ('25', 'User Slot 25'),
        ('26', 'User Slot 26'),
        ('27', 'User Slot 27'),
        ('28', 'User Slot 28'),
        ('29', 'User Slot 29'),
        ('100', 'Camera Temp'),
        ('101', 'Future Use 1'),
        ('102', 'Future Use 2'),
        ('103', 'Future Use 3'),
        ('104', 'Future Use 4'),
        ('105', 'Future Use 5'),
        ('106', 'Future Use 6'),
        ('107', 'Future Use 7'),
        ('108', 'Future Use 8'),
        ('109', 'Future Use 9'),
        ('110', 'System Temp 10'),
        ('111', 'System Temp 11'),
        ('112', 'System Temp 12'),
        ('113', 'System Temp 13'),
        ('114', 'System Temp 14'),
        ('115', 'System Temp 15'),
        ('116', 'System Temp 16'),
        ('117', 'System Temp 17'),
        ('118', 'System Temp 18'),
        ('119', 'System Temp 19'),
        ('120', 'System Temp 20'),
        ('121', 'System Temp 21'),
        ('122', 'System Temp 22'),
        ('123', 'System Temp 23'),
        ('124', 'System Temp 24'),
        ('125', 'System Temp 25'),
        ('126', 'System Temp 26'),
        ('127', 'System Temp 27'),
        ('128', 'System Temp 28'),
        ('129', 'System Temp 29'),
    ]


    def __init__(self):
        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
                #logger.info('Loaded config id: %d', self._config_obj.config_id)
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config

            self._device_name = 'indi-allsky'

        self._port = 1883


    @property
    def device_name(self):
        return self._device_name

    @device_name.setter
    def device_name(self, new_device_name):
        self._device_name = str(new_device_name)


    def main(self, retain=True):
        if not self.config['MQTTPUBLISH'].get('ENABLE'):
            logger.error('MQ Publishing not enabled')
            sys.exit(1)


        transport = self.config['MQTTPUBLISH']['TRANSPORT']
        hostname = self.config['MQTTPUBLISH']['HOST']
        port = self.config['MQTTPUBLISH']['PORT']
        username = self.config['MQTTPUBLISH']['USERNAME']
        password = self.config['MQTTPUBLISH']['PASSWORD']
        tls = self.config['MQTTPUBLISH']['TLS']
        cert_bypass = self.config['MQTTPUBLISH'].get('CERT_BYPASS', True)

        base_topic  = self.config['MQTTPUBLISH']['BASE_TOPIC']


        if port:
            self._port = port


        self.update_sensor_slot_labels()


        print('')
        print('#################################################')
        print('##### Home Assistant Discovery Setup Script #####')
        print('#################################################')
        print('')
        print('Transport: {0}'.format(transport))
        print('Hostname: {0}'.format(hostname))
        print('Port: {0}'.format(port))
        print('TLS: {0}'.format(str(tls)))
        print('Username: {0}'.format(username))
        print('')
        print('Auto-discovery base topic: {0}'.format(self.discovery_base_topic))
        print('Device name:               {0}'.format(self.device_name))
        print('')
        print('indi-allsky base topic:    {0}'.format(base_topic))
        print('')

        print('Setup proceeding in 10 seconds... (control-c to cancel)')


        time.sleep(10.0)


        basic_sensor_list = [
            {
                'component' : 'image',
                'object_id' : 'indi_allsky_latest',
                'config' : {
                    'name' : "indi-allsky Camera",
                    'unique_id' : 'indi_allsky_latest_{0}'.format(self.unique_id_base),
                    'content_type' : 'image/jpeg',
                    #'content_type' : 'image/png',
                    'image_topic' : '/'.join((base_topic, 'latest')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_exp_date',
                'config' : {
                    'name' : 'Exposure Date',
                    'unique_id' : 'indi_allsky_exp_date_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'exp_date')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_exposure',
                'config' : {
                    'name' : 'Exposure',
                    'unit_of_measurement' : 's',
                    'unique_id' : 'indi_allsky_exposure_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'exposure')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_gain',
                'config' : {
                    'name' : 'Camera Gain',
                    'unique_id' : 'indi_allsky_gain_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'gain')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_bin',
                'config' : {
                    'name' : 'Camera Binmode',
                    'unique_id' : 'indi_allsky_bin_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'bin')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_temp',
                'config' : {
                    'name' : 'Camera Temp',
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_temp_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'temp')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_sunalt',
                'config' : {
                    'name' : 'Sun Altitude',
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_sunalt_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'sunalt')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_moonalt',
                'config' : {
                    'name' : 'Moon Altitude',
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_moonalt_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'moonalt')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_moonphase',
                'config' : {
                    'name' : 'Moon Phase',
                    'unit_of_measurement' : '%',
                    'unique_id' : 'indi_allsky_moonphase_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'moonphase')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'binary_sensor',
                'object_id' : 'indi_allsky_moonmode',
                'config' : {
                    'name' : 'Moon Mode',
                    'payload_on' : True,
                    'payload_off' : False,
                    'unique_id' : 'indi_allsky_moonmode_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'moonmode')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'binary_sensor',
                'object_id' : 'indi_allsky_night',
                'config' : {
                    'name' : 'Night',
                    'payload_on' : True,
                    'payload_off' : False,
                    'unique_id' : 'indi_allsky_night_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'night')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_sqm',
                'config' : {
                    'name' : 'SQM',
                    'unique_id' : 'indi_allsky_sqm_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'sqm')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_stars',
                'config' : {
                    'name' : 'Stars',
                    'unique_id' : 'indi_allsky_stars_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'stars')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_latitude',
                'config' : {
                    'name' : 'Latitude',
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_latitude_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'latitude')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_longitude',
                'config' : {
                    'name' : 'Longitude',
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_longitude_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'longitude')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_elevation',
                'config' : {
                    'name' : 'Elevation',
                    'unit_of_measurement' : 'm',
                    'unique_id' : 'indi_allsky_elevation_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'elevation')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_kpindex',
                'config' : {
                    'name' : 'K-P Index',
                    'unique_id' : 'indi_allsky_kpindex_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'kpindex')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_ovation_max',
                'config' : {
                    'name' : 'Aurora',
                    'unit_of_measurement' : '%',
                    'unique_id' : 'indi_allsky_ovation_max_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'ovation_max')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_smoke_rating',
                'config' : {
                    'name' : 'Smoke Rating',
                    'unique_id' : 'indi_allsky_smoke_rating_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'smoke_rating')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_sidereal_time',
                'config' : {
                    'name' : 'Sidereal Time',
                    'unique_id' : 'indi_allsky_sidereal_time_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'sidereal_time')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
        ]


        if self.config['FISH2PANO'].get('ENABLE'):
            basic_sensor_list.append({
                'component' : 'image',
                'object_id' : 'indi_allsky_panorama',
                'config' : {
                    'name' : "indi-allsky Panorama",
                    'unique_id' : 'indi_allsky_panorama_{0}'.format(self.unique_id_base),
                    'content_type' : 'image/jpeg',
                    #'content_type' : 'image/png',
                    'image_topic' : '/'.join((base_topic, 'panorama')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            })


        extended_sensor_list = [
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_cpu_total',
                'config' : {
                    'name' : 'CPU Total',
                    'unique_id' : 'indi_allsky_cpu_total_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'cpu', 'total')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
            {
                'component' : 'sensor',
                'object_id' : 'indi_allsky_memory_total',
                'config' : {
                    'name' : 'Memory Total',
                    'unit_of_measurement' : '%',
                    'unique_id' : 'indi_allsky_memory_total_{0}'.format(self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'memory', 'total')),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            },
        ]


        fs_list = psutil.disk_partitions()

        for fs in fs_list:
            if fs.mountpoint.startswith('/snap/'):
                # skip snap filesystems
                continue

            try:
                psutil.disk_usage(fs.mountpoint)
            except PermissionError as e:
                logger.error('PermissionError: %s', str(e))
                continue

            if fs.mountpoint == '/':
                extended_sensor_list.append({
                    'component' : 'sensor',
                    'object_id' : 'indi_allsky_root_fs',
                    'config' : {
                        'name' : 'Filesystem /',
                        'unit_of_measurement' : '%',
                        'unique_id' : 'indi_allsky_fs_root_{0}'.format(self.unique_id_base),
                        'state_topic' : '/'.join((base_topic, 'disk', 'root')),
                        'device'   : {
                            'name' : self.device_name,
                            'identifiers' : [
                                self.device_name,
                            ],
                        },
                    },
                })


            else:
                # remove slashes
                fs_mountpoint_safe = re.sub(r'/\.', '__', fs.mountpoint)

                extended_sensor_list.append({
                    'component' : 'sensor',
                    'object_id' : 'indi_allsky_fs_{0}'.format(fs_mountpoint_safe),
                    'config' : {
                        'name' : 'Filesystem {0}'.format(fs.mountpoint),
                        'unit_of_measurement' : '%',
                        'unique_id' : 'indi_allsky_fs_{0}_{1}'.format(fs_mountpoint_safe, self.unique_id_base),
                        'state_topic' : '/'.join((base_topic, 'disk', re.sub(r'^/', '', fs.mountpoint))),  # remove slash prefix
                        'device'   : {
                            'name' : self.device_name,
                            'identifiers' : [
                                self.device_name,
                            ],
                        },
                    },
                })




        temp_info = psutil.sensors_temperatures()

        for t_key in sorted(temp_info):  # always return the keys in the same order
            for i, t in enumerate(temp_info[t_key]):
                if not t.label:
                    # use index for label name
                    label = str(i)
                else:
                    label = t.label


                t_key_safe = re.sub(r'[#+\$\*\>\.\ ]', '_', t_key)
                label_safe = re.sub(r'[#+\$\*\>\.\ ]', '_', label)


                extended_sensor_list.append({
                    'component' : 'sensor',
                    'object_id' : 'indi_allsky_thermal_{0}_{1}'.format(t_key_safe, label_safe),
                    'config' : {
                        'name' : 'Thermal {0} {1}'.format(t_key, label),
                        'unit_of_measurement' : '°',
                        'unique_id' : 'indi_allsky_thermal_{0}_{1}_{2}'.format(t_key_safe, label_safe, self.unique_id_base),
                        'state_topic' : '/'.join((base_topic, 'temp', t_key_safe, label_safe)),
                        'device'   : {
                            'name' : self.device_name,
                            'identifiers' : [
                                self.device_name,
                            ],
                        },
                    },
                })


        # system temp sensors
        for i in range(30):
            extended_sensor_list.append({
                'component' : 'sensor',
                'object_id' : 'indi_allsky_sensor_temp_{0}'.format(i),
                'config' : {
                    'name' : self.SENSOR_SLOT_choices[i + 30][1],
                    'unit_of_measurement' : '°',
                    'unique_id' : 'indi_allsky_sensor_temp_{0}_{1}'.format(i, self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'sensor_temp_{0}'.format(str(i)))),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            })


        # user sensors
        for i in range(30):
            extended_sensor_list.append({
                'component' : 'sensor',
                'object_id' : 'indi_allsky_sensor_user_{0}'.format(i),
                'config' : {
                    'name' : self.SENSOR_SLOT_choices[i][1],
                    'unique_id' : 'indi_allsky_sensor_user_{0}_{1}'.format(i, self.unique_id_base),
                    'state_topic' : '/'.join((base_topic, 'sensor_user_{0}'.format(str(i)))),
                    'device'   : {
                        'name' : self.device_name,
                        'identifiers' : [
                            self.device_name,
                        ],
                    },
                },
            })


        message_list = list()
        for sensor in basic_sensor_list:
            message = {
                'topic'    : '/'.join((self.discovery_base_topic, sensor['component'], base_topic, sensor['object_id'], 'config')),
                'payload'  : json.dumps(sensor['config']),
                'qos'      : 0,
                'retain'   : retain,
            }
            message_list.append(message)

            logger.warning('Create topic: %s', message['topic'])
            #logger.warning('Data: %s', pformat(message))


        for sensor in extended_sensor_list:
            message = {
                'topic'    : '/'.join((self.discovery_base_topic, sensor['component'], base_topic, sensor['object_id'], 'config')),
                'payload'  : json.dumps(sensor['config']),
                'qos'      : 0,
                'retain'   : retain,
            }

            message_list.append(message)

            logger.warning('Create topic: %s', message['topic'])
            #logger.warning('Data: %s', pformat(message))


        #logger.warning('Messages: %s', pformat(message_list))


        mq_auth = None
        mq_tls = None

        if tls:
            mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                #'tls_version' : ssl.PROTOCOL_TLSv1_2,
                'cert_reqs'   : ssl.CERT_REQUIRED,
                'insecure'    : False,
            }

            if cert_bypass:
                mq_tls['cert_reqs'] = ssl.CERT_NONE
                mq_tls['insecure'] = True



        if username:
            mq_auth = {
                'username' : username,
                'password' : password,
            }



        logger.warning('Publishing discovery data')
        publish.multiple(
            message_list,
            transport=transport,
            hostname=hostname,
            port=self._port,
            client_id='',
            keepalive=60,
            auth=mq_auth,
            tls=mq_tls,
        )


    def update_sensor_slot_labels(self):
        from indi_allsky.devices import sensors as indi_allsky_sensors

        temp_sensor__a_classname = self.config.get('TEMP_SENSOR', {}).get('A_CLASSNAME', '')
        temp_sensor__a_label = self.config.get('TEMP_SENSOR', {}).get('A_LABEL', 'Sensor A')
        temp_sensor__a_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('A_USER_VAR_SLOT')
        temp_sensor__b_classname = self.config.get('TEMP_SENSOR', {}).get('B_CLASSNAME', '')
        temp_sensor__b_label = self.config.get('TEMP_SENSOR', {}).get('B_LABEL', 'Sensor B')
        temp_sensor__b_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('B_USER_VAR_SLOT')
        temp_sensor__c_classname = self.config.get('TEMP_SENSOR', {}).get('C_CLASSNAME', '')
        temp_sensor__c_label = self.config.get('TEMP_SENSOR', {}).get('C_LABEL', 'Sensor C')
        temp_sensor__c_user_var_slot = self.config.get('TEMP_SENSOR', {}).get('C_USER_VAR_SLOT')


        # fix system temp offset
        if temp_sensor__a_user_var_slot >= 100:
            temp_sensor__a_user_var_slot -= 79

        if temp_sensor__b_user_var_slot >= 100:
            temp_sensor__b_user_var_slot -= 79

        if temp_sensor__c_user_var_slot >= 100:
            temp_sensor__c_user_var_slot -= 79


        if temp_sensor__a_classname:
            try:
                temp_sensor__a_class = getattr(indi_allsky_sensors, temp_sensor__a_classname)

                for x in range(temp_sensor__a_class.METADATA['count']):
                    self.SENSOR_SLOT_choices[temp_sensor__a_user_var_slot + x] = (
                        str(temp_sensor__a_user_var_slot + x),
                        '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__a_class.METADATA['name'],
                            temp_sensor__a_label,
                            temp_sensor__a_class.METADATA['labels'][x],
                        )
                    )
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__a_classname)


        if temp_sensor__b_classname:
            try:
                temp_sensor__b_class = getattr(indi_allsky_sensors, temp_sensor__b_classname)

                for x in range(temp_sensor__b_class.METADATA['count']):
                    self.SENSOR_SLOT_choices[temp_sensor__b_user_var_slot + x] = (
                        str(temp_sensor__b_user_var_slot + x),
                        '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__b_class.METADATA['name'],
                            temp_sensor__b_label,
                            temp_sensor__b_class.METADATA['labels'][x],
                        )
                    )
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__a_classname)


        if temp_sensor__c_classname:
            try:
                temp_sensor__c_class = getattr(indi_allsky_sensors, temp_sensor__c_classname)

                for x in range(temp_sensor__c_class.METADATA['count']):
                    self.SENSOR_SLOT_choices[temp_sensor__c_user_var_slot + x] = (
                        str(temp_sensor__c_user_var_slot + x),
                        '{0:s} - {1:s} - {2:s}'.format(
                            temp_sensor__c_class.METADATA['name'],
                            temp_sensor__c_label,
                            temp_sensor__c_class.METADATA['labels'][x],
                        )
                    )
            except AttributeError:
                logger.error('Unknown sensor class: %s', temp_sensor__a_classname)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--device_topic',
        '-d',
        help='device name topic',
        type=str,
        default='indi-allsky',
    )

    retain_group = argparser.add_mutually_exclusive_group(required=False)
    retain_group.add_argument(
        '--retain',
        help='Enable retain flag on discovery topics (default)',
        dest='retain',
        action='store_true',
    )
    retain_group.add_argument(
        '--no-retain',
        help='Disable retain flag on discovery topics',
        dest='retain',
        action='store_false',
    )
    retain_group.set_defaults(retain=True)

    args = argparser.parse_args()


    had = HADiscovery()
    had.device_topic = args.device_topic
    had.main(retain=args.retain)

