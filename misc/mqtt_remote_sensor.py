#!/usr/bin/env python3
############################################
# Publishes sensor data to MQTT            #
############################################


### Requirements
#pip3 install paho-mqtt ephem circuitpython-bmp180 adafruit-circuitpython-bmp280 adafruit-circuitpython-bme280 adafruit-circuitpython-bme680 adafruit-circuitpython-ahtx0 adafruit-circuitpython-tsl2591


import os

### MQTT settings
MQTT_TRANSPORT = os.environ.get('MQTT_TRANSPORT', 'tcp')
MQTT_PROTOCOL = os.environ.get('MQTT_PROTOCOL', 'MQTTv5')
MQTT_HOSTNAME = os.environ.get('MQTT_HOSTNAME', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 8883))
MQTT_USERNAME = os.environ.get('MQTT_USERNAME', 'CHANGEME')
MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD', 'CHANGEME')
MQTT_QOS = int(os.environ.get('MQTT_QOS', 0))
MQTT_TLS = int(os.environ.get('MQTT_TLS', 1))
MQTT_CERT_BYPASS = int(os.environ.get('MQTT_CERT_BYPASS', 1))

TEMP_DISPLAY = os.environ.get('TEMP_DISPLAY', 'c')  # c, f, or k
PRESSURE_DISPLAY = os.environ.get('PRESSURE_DISPLAY', 'hPa')  # hPa, psi, inHg, or mmHg

LATITUDE = os.environ.get('LATITUDE', 33.0)
LONGITUDE = os.environ.get('LONGITUDE', -84.0)


import sys
import argparse
import time
from datetime import datetime
from datetime import timezone
import math
import ephem
import socket
import ssl
import paho.mqtt.client as mqtt
import signal
import logging


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class MqttRemoteSensorBase(object):
    base_topic = None
    name = ''  # just to fix copy/paste errors


    def __init__(self):
        self.client = None

        self._i2c_address = 0


        self.next_update_time = time.time()  # immediately
        self.update_offset = 15  # seconds


        self.astro_darkness = None  # force update immediately

        self.obs = ephem.Observer()
        self.obs.lon = math.radians(LONGITUDE)
        self.obs.lat = math.radians(LATITUDE)

        # disable atmospheric refraction calcs
        self.obs.pressure = 0

        self.sun = ephem.Sun()


        self._shutdown = False


    @property
    def i2c_address(self):
        return self._i2c_address

    @i2c_address.setter
    def i2c_address(self, new_i2c_address):
        self._i2c_address = int(new_i2c_address, 16)


    @property
    def sun_alt(self):
        self.obs.date = datetime.now(tz=timezone.utc)  # ephem expects UTC dates
        self.sun.compute(self.obs)
        return math.degrees(self.sun.alt)


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')
        self._shutdown = True


    def run(self):
        logger.info('MQTT_TRANSPORT:   %s', MQTT_TRANSPORT)
        logger.info('MQTT_PROTOCOL:    %s', MQTT_PROTOCOL)
        logger.info('MQTT_HOSTNAME:    %s', MQTT_HOSTNAME)
        logger.info('MQTT_PORT:        %d', MQTT_PORT)
        logger.info('MQTT_USERNAME:    %s', MQTT_USERNAME)
        logger.info('MQTT_PASSWORD:    %s', '********')
        logger.info('MQTT_TLS:         %s', str(bool(MQTT_TLS)))
        logger.info('BASE_TOPIC:       %s', self.base_topic)
        logger.info('TEMP_DISPLAY:     %s', TEMP_DISPLAY)
        logger.info('PRESSURE_DISPLAY: %s', PRESSURE_DISPLAY)
        logger.info('LATITUDE:         %s', LATITUDE)
        logger.info('LONGITUDE:        %s', LONGITUDE)
        time.sleep(3.0)


        try:
            self.init_sensor()
        except (OSError, ValueError) as e:
            logger.error('Error initializing gpio controller: %s', str(e))
            sys.exit(1)
        except DeviceControlException as e:
            logger.error('Error initializing gpio controller: %s', str(e))
            sys.exit(1)


        try:
            protocol = getattr(mqtt, MQTT_PROTOCOL)
        except AttributeError:
            logger.error('Unknown MQTT Protocol: %s', MQTT_PROTOCOL)
            sys.exit(1)


        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=protocol,
            transport=MQTT_TRANSPORT,
        )


        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish
        #self.client.on_message = self.on_message
        #self.client.on_subscribe = self.on_subscribe
        #self.client.on_unsubscribe = self.on_unsubscribe


        if MQTT_USERNAME:
            self.client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)


        if MQTT_TLS:
            mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
            }

            if MQTT_CERT_BYPASS:
                mq_tls['cert_reqs'] = ssl.CERT_NONE

            self.client.tls_set(**mq_tls)


        try:
            self.client.connect(MQTT_HOSTNAME, port=MQTT_PORT)
        except ConnectionRefusedError as e:
            # log the error, client will continue to try to connect
            logger.error('ConnectionRefusedError: %s', str(e))
        except socket.gaierror as e:
            logger.error('socket.gaierror: %s', str(e))
            sys.exit(1)
        except TimeoutError as e:
            logger.error('TimeoutError: %s', str(e))
            sys.exit(1)
        except ssl.SSLCertVerificationError as e:
            logger.error('SSLCertVerificationError: %s', str(e))
            sys.exit(1)


        signal.signal(signal.SIGINT, self.sigint_handler)
        signal.signal(signal.SIGTERM, self.sigint_handler)


        self.client.loop_start()


        ### Main program loop
        while True:
            if self._shutdown:
                break


            now_time = time.time()
            if now_time < self.next_update_time:
                time.sleep(0.1)
                continue


            self.next_update_time = now_time + self.update_offset


            try:
                sensor_data_dict = self.update_sensor()
            except SensorReadException as e:
                logger.error('SensorReadException: {0:s}'.format(str(e)))
                continue
            except OSError as e:
                logger.error('Sensor OSError: {0:s}'.format(str(e)))
                continue
            except IOError as e:
                logger.error('Sensor IOError: {0:s}'.format(str(e)))
                continue
            except IndexError as e:
                logger.error('Sensor slot error: {0:s}'.format(str(e)))
                continue


            for entry, v in sensor_data_dict.items():
                topic = '/'.join([self.base_topic, entry])
                logger.info('Publishing: %s', topic)

                self.client.publish(
                    topic,
                    payload=float(v),
                    qos=MQTT_QOS,
                    retain=False,
                )


        ### Shutdown
        self.client.disconnect()
        self.client.loop_stop()
        self.deinit_sensor()


    def init_sensor(self):
        raise Exception('Override in sensor class')


    def update_sensor(self):
        raise Exception('Override in sensor class')


    def on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        # only report a single channel
        if reason_code_list[0].is_failure:
            logger.error('Broker rejected you subscription: %s', reason_code_list[0])
        else:
            logger.info('Broker granted the following QoS: %d', reason_code_list[0].value)


    def on_unsubscribe(self, client, userdata, mid, reason_code_list, properties):
        # Be careful, the reason_code_list is only present in MQTTv5.
        # In MQTTv3 it will always be empty
        if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
            logger.info('unsubscribe succeeded')
        else:
            logger.error('Broker replied with failure: %s', reason_code_list[0])

        client.disconnect()


    def on_message(self, client, userdata, message):
        #logger.info('MQTT message')
        pass


    def on_publish(self, client, userdata, mid, reason_code, properties):
        #logger.info('MQTT message published')
        pass


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            # we should always subscribe from on_connect callback to be sure
            # our subscribed is persisted across reconnections.
            pass


    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.error('MQTT disconnected: %s', reason_code)



    ### basic stuff


    def deinit_sensor(self):
        pass


    def c2f(self, c):
        # celsius to fahrenheit
        return (c * 9.0 / 5.0) + 32


    def f2c(self, f):
        # fahrenheit to celsius
        return (f - 32) * 5.0 / 9.0


    def c2k(self, c):
        # celsius to kelvin
        return c + 273.15


    def k2c(self, k):
        # kelvin to celsius
        return k - 273.15


    def f2k(self, f):
        # fahrenheit to kelvin
        return (f - 32) * 5 / 9 + 273.15


    def hPa2psi(self, hpa):
        # hectopascals to pounds/sq in
        return hpa * 0.014503768077999999


    def hPa2inHg(self, hpa):
        # hectopascals to inches mercury
        return hpa * 0.02952998057228486


    def hPa2mmHg(self, hpa):
        # hectopascals to millimeters mercury
        return hpa * 0.7500637554192107


    def inHg2mb(self, inHg):
        # inches mercurty to millibars mercury
        return inHg * 0.029529983071445


    def inHg2psi(self, inHg):
        # inches mercurty to pounds/sq in
        return inHg * 14.5037744


    def inHg2hpa(self, inHg):
        # inches mercurty to hectpascals
        return inHg * 33.86389


    def inHg2mmHg(self, inHg):
        # inches mercury to millimeters mercury
        return inHg * 25.400


    def mps2kmph(self, mps):
        # meters/sec to kilometers/hour
        return mps * 3.6


    def kmph2miph(self, kmph):
        # kilometers/hour to miles/hour
        return kmph * 0.6213711922


    def km2mi(self, km):
        # kilometers to miles
        return self.kmph2miph(km)


    def mps2miph(self, mps):
        # meters/sec to miles/hour
        return mps * 3.6 * 0.6213711922


    def mps2knots(self, mps):
        # meters/sec to knots
        return mps * 1.9438445


    def mph2knots(self, mph):
        # miles/hour to knots
        return mph * 0.8689762419


    def mph2kph(self, mph):
        # miles/hour to kilometers/hour
        return mph * 1.609344


    def mph2mps(self, mph):
        # miles/hour to meters/second
        return mph * 0.44704


    def mm2in(self, mm):
        # millimeters to inches
        return mm * 0.0393700787


    def lux2mag(self, lux):
        raw_mag = (math.log10(lux) * 2.5) * -1
        logger.warning('Lux Raw Magnitude: %0.2f', raw_mag)

        return self._lux_magnitude_offset + raw_mag, raw_mag  # array, raw_mag is negative


    ###
    ### https://github.com/gregnau/heat-index-calc/blob/master/heat-index-calc.py
    ###


    def get_heat_index_f(self, temp_f, rh):
        T2 = pow(temp_f, 2)
        #T3 = pow(temp_f, 3)
        H2 = pow(rh, 2)
        #H3 = pow(rh, 3)


        # Coefficients for the calculations
        C1_f = [ -42.379, 2.04901523, 10.14333127, -0.22475541, -6.83783e-03, -5.481717e-02, 1.22874e-03, 8.5282e-04, -1.99e-06]
        #C2_f = [ 0.363445176, 0.988622465, 4.777114035, -0.114037667, -0.000850208, -0.020716198, 0.000687678, 0.000274954, 0]
        #C3_f = [ 16.923, 0.185212, 5.37941, -0.100254, 0.00941695, 0.00728898, 0.000345372, -0.000814971, 0.0000102102, -0.000038646, 0.0000291583, 0.00000142721, 0.000000197483, -0.0000000218429, 0.000000000843296, -0.0000000000481975]


        heatindex1_f = C1_f[0] + (C1_f[1] * temp_f) + (C1_f[2] * rh) + (C1_f[3] * temp_f * rh) + (C1_f[4] * T2) + (C1_f[5] * H2) + (C1_f[6] * T2 * rh) + (C1_f[7] * temp_f * H2) + (C1_f[8] * T2 * H2)
        #heatindex2_f = C2_f[0] + (C2_f[1] * temp_f) + (C2_f[2] * rh) + (C2_f[3] * temp_f * rh) + (C2_f[4] * T2) + (C2_f[5] * H2) + (C2_f[6] * T2 * rh) + (C2_f[7] * temp_f * H2) + (C2_f[8] * T2 * H2)
        #heatindex3_f = C3_f[0] + (C3_f[1] * temp_f) + (C3_f[2] * rh) + (C3_f[3] * temp_f * rh) + (C3_f[4] * T2) + (C3_f[5] * H2) + (C3_f[6] * T2 * rh) + (C3_f[7] * temp_f * H2) + (C3_f[8] * T2 * H2) + (C3_f[9] * T3) + (C3_f[10] * H3) + (C3_f[11] * T3 * rh) + (C3_f[12] * temp_f * H3) + (C3_f[13] * T3 * H2) + (C3_f[14] * T2 * H3) + (C3_f[15] * T3 * H3)


        return heatindex1_f


    def get_heat_index_c(self, temp_c, rh):
        temp_f = self.c2f(temp_c)

        heat_index_f = self.get_heat_index_f(temp_f, rh)

        return self.f2c(heat_index_f)



    ###
    ### https://gist.github.com/sourceperl/45587ea99ff123745428
    ###


    def get_frost_point_c(self, t_air_c, dew_point_c):
        """Compute the frost point in degrees Celsius
        :param t_air_c: current ambient temperature in degrees Celsius
        :type t_air_c: float
        :param dew_point_c: current dew point in degrees Celsius
        :type dew_point_c: float
        :return: the frost point in degrees Celsius
        :rtype: float
        """
        dew_point_k = 273.15 + dew_point_c
        t_air_k = 273.15 + t_air_c
        frost_point_k = dew_point_k - t_air_k + 2671.02 / ((2954.61 / t_air_k) + 2.193665 * math.log(t_air_k) - 13.3448)
        return frost_point_k - 273.15


    def get_dew_point_c(self, t_air_c, rel_humidity):
        """Compute the dew point in degrees Celsius
        :param t_air_c: current ambient temperature in degrees Celsius
        :type t_air_c: float
        :param rel_humidity: relative humidity in %
        :type rel_humidity: float
        :return: the dew point in degrees Celsius
        :rtype: float
        """
        A = 17.27
        B = 237.7
        alpha = ((A * t_air_c) / (B + t_air_c)) + math.log(rel_humidity / 100.0)
        return (B * alpha) / (A - alpha)


class MqttRemoteSensorBmp180_I2C(MqttRemoteSensorBase):
    base_topic = 'bmp180'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorBmp180_I2C, self).__init__(*args, **kwargs)

        self.bmp180 = None


    def init_sensor(self):
        import board
        #import busio
        import bmp180

        logger.warning('Initializing BMP180 I2C temperature device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.bmp180 = bmp180.BMP180(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


    def update_sensor(self):
        try:
            temp_c = float(self.bmp180.temperature)
            pressure_hpa = float(self.bmp180.pressure)  # hPa
            #altitude = float(self.bmp180.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('BMP180 - temp: %0.1fc, pressure: %0.1fhPa', temp_c, pressure_hpa)

        # no humidity sensor


        if TEMP_DISPLAY == 'f':
            current_temp = self.c2f(temp_c)
        elif TEMP_DISPLAY == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        if PRESSURE_DISPLAY == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif PRESSURE_DISPLAY == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif PRESSURE_DISPLAY == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'temperature'       : current_temp,
            'pressure'          : current_pressure,
        }

        return data


class MqttRemoteSensorBmp280_I2C(MqttRemoteSensorBase):
    base_topic = 'bmp280'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorBmp280_I2C, self).__init__(*args, **kwargs)

        self.bmp280 = None


    def init_sensor(self):
        import board
        #import busio
        import adafruit_bmp280

        logger.warning('Initializing BMP280 I2C temperature device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.bmp280.overscan_temperature = adafruit_bmp280.OVERSCAN_X1
        self.bmp280.overscan_pressure = adafruit_bmp280.OVERSCAN_X16
        self.bmp280.iir_filter = adafruit_bmp280.IIR_FILTER_DISABLE


        # throw away
        self.bmp280.temperature
        self.bmp280.pressure

        time.sleep(1)  # allow things to settle


    def update_sensor(self):
        try:
            temp_c = float(self.bmp280.temperature)
            pressure_hpa = float(self.bmp280.pressure)  # hPa
            #altitude = float(self.bmp280.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('BMP280 - temp: %0.1fc, pressure: %0.1fhPa', temp_c, pressure_hpa)


        if TEMP_DISPLAY == 'f':
            current_temp = self.c2f(temp_c)
        elif TEMP_DISPLAY == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        if PRESSURE_DISPLAY == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif PRESSURE_DISPLAY == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif PRESSURE_DISPLAY == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'temperature'       : current_temp,
            'pressure'          : current_pressure,
        }

        return data


class MqttRemoteSensorBme280_I2C(MqttRemoteSensorBase):
    base_topic = 'bme280'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorBme280_I2C, self).__init__(*args, **kwargs)

        self.bme280 = None


    def init_sensor(self):
        import board
        #import busio
        from adafruit_bme280 import advanced as adafruit_bme280

        logger.warning('Initializing BME280 I2C temperature device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.bme280.overscan_humidity = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_temperature = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_pressure = adafruit_bme280.OVERSCAN_X16
        self.bme280.iir_filter = adafruit_bme280.IIR_FILTER_DISABLE


        # throw away
        self.bme280.temperature
        self.bme280.humidity
        self.bme280.pressure

        time.sleep(1)  # allow things to settle


    def update_sensor(self):
        try:
            temp_c = float(self.bme280.temperature)
            rel_h = float(self.bme280.humidity)
            pressure_hpa = float(self.bme280.pressure)  # hPa
            #altitude = float(self.bme280.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('BME280 - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa', temp_c, rel_h, pressure_hpa)

        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(temp_c, rel_h)


        if TEMP_DISPLAY == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
        elif TEMP_DISPLAY == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c
            current_hi = heat_index_c


        if PRESSURE_DISPLAY == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif PRESSURE_DISPLAY == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif PRESSURE_DISPLAY == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'temperature'       : current_temp,
            'relative_humdity'  : rel_h,
            'pressure'          : current_pressure,
            'dew_point'         : current_dp,
            'frost_point'       : current_fp,
            'heat_index'        : current_hi,
        }

        return data


class MqttRemoteSensorBme680_I2C(MqttRemoteSensorBase):
    base_topic = 'bme680'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorBme680_I2C, self).__init__(*args, **kwargs)

        self.bme680 = None


    def init_sensor(self):
        import board
        #import busio
        import adafruit_bme680

        logger.warning('Initializing BME680 I2C temperature device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.bme680.humidity_oversample = 2
        self.bme680.pressure_oversample = 4
        self.bme680.temperature_oversample = 8
        self.bme680.filter_size = 3


        # throw away, initial humidity reading is always 100%
        self.bme680.temperature
        self.bme680.humidity
        self.bme680.pressure
        self.bme680.gas

        time.sleep(1)  # allow things to settle


    def update_sensor(self):
        try:
            temp_c = float(self.bme680.temperature)
            rel_h = float(self.bme680.humidity)
            pressure_hpa = float(self.bme680.pressure)  # hPa
            gas_ohm = float(self.bme680.gas)  # ohm
            #altitude = float(self.bme680.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('BME680 - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa, gas: %0.1f', temp_c, rel_h, pressure_hpa, gas_ohm)

        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(temp_c, rel_h)


        if TEMP_DISPLAY == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
        elif TEMP_DISPLAY == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c
            current_hi = heat_index_c


        if PRESSURE_DISPLAY == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif PRESSURE_DISPLAY == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif PRESSURE_DISPLAY == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'temperature'       : current_temp,
            'relative_humdity'  : rel_h,
            'pressure'          : current_pressure,
            'gas_ohm'           : gas_ohm,
            'dew_point'         : current_dp,
            'frost_point'       : current_fp,
            'heat_index'        : current_hi,
        }

        return data


class MqttRemoteSensorAhtx0_I2C(MqttRemoteSensorBase):
    base_topic = 'ahtx0'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorAhtx0_I2C, self).__init__(*args, **kwargs)

        self.aht = None


    def init_sensor(self):
        import board
        #import busio
        import adafruit_ahtx0

        logger.warning('Initializing AHTx0 I2C temperature device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.aht = adafruit_ahtx0.AHTx0(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


    def update_sensor(self):
        try:
            temp_c = float(self.aht.temperature)
            rel_h = float(self.aht.relative_humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('AHTx0 - temp: %0.1fc, humidity: %0.1f%%', temp_c, rel_h)


        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(temp_c, rel_h)


        if TEMP_DISPLAY == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
        elif TEMP_DISPLAY == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c
            current_hi = heat_index_c


        data = {
            'temperature'       : current_temp,
            'relative_humdity'  : rel_h,
            'dew_point'         : current_dp,
            'frost_point'       : current_fp,
            'heat_index'        : current_hi,
        }

        return data


class MqttRemoteSensorTsl2591_I2C(MqttRemoteSensorBase):
    base_topic = 'tsl2591'

    def __init__(self, *args, **kwargs):
        super(MqttRemoteSensorTsl2591_I2C, self).__init__(*args, **kwargs)

        self.tsl2591 = None


    def init_sensor(self):
        import board
        #import busio
        import adafruit_tsl2591

        logger.warning('Initializing TSL2591 I2C light sensor device @ %s', hex(self.i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.tsl2591 = adafruit_tsl2591.TSL2591(i2c, address=self.i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.gain_night = getattr(adafruit_tsl2591, 'GAIN_MED')
        self.gain_day = getattr(adafruit_tsl2591, 'GAIN_LOW')
        self.integration_night = getattr(adafruit_tsl2591, 'INTEGRATIONTIME_100MS')
        self.integration_day = getattr(adafruit_tsl2591, 'INTEGRATIONTIME_100MS')


        ### You can optionally change the gain and integration time:
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_LOW   # (1x gain)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_MED   # (25x gain, the default)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_HIGH  # (428x gain)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_MAX   # (9876x gain)

        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_100MS  # (100ms, default)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_200MS  # (200ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_300MS  # (300ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_400MS  # (400ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_500MS  # (500ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_600MS  # (600ms)


        time.sleep(1)


    def update_sensor(self):
        astro_darkness = self.sun_alt <= 18.0
        if self.astro_darkness != astro_darkness:
            self.astro_darkness = astro_darkness
            self.update_sensor_settings()


        #gain = self.tsl2591.gain
        #integration = self.tsl2591.integration_time
        #logger.info('[%s] TSL2591 settings - Gain: %d, Integration: %d', gain, integration)


        try:
            lux = float(self.tsl2591.lux)
            infrared = int(self.tsl2591.infrared)
            visible = int(self.tsl2591.visible)
            full_spectrum = int(self.tsl2591.full_spectrum)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('TSL2591 - lux: %0.4f, visible: %d, ir: %d, full: %d', lux, visible, infrared, full_spectrum)


        if self.astro_darkness:
            try:
                sqm_mag, raw_mag = self.lux2mag(lux)
            except ValueError as e:
                logger.error('SQM calculation error - ValueError: %s', str(e))
                sqm_mag = 0.0
                raw_mag = 0.0
        else:
            # disabled outside astronomical darkness
            sqm_mag = 0.0
            raw_mag = 0.0


        data = {
            'lux'           : lux,
            'visible'       : visible,
            'infrared'      : infrared,
            'full_spectrum' : full_spectrum,
            'sqm_magnitude' : sqm_mag,
            'raw_magnitude' : raw_mag,
        }


        return data



    def update_sensor_settings(self):
        if self.astro_darkness:
            logger.info('Switching TSL2591 to night mode - Gain %d, Integration: %d', self.gain_night, self.integration_night)
            self.tsl2591.gain = self.gain_night
            self.tsl2591.integration_time = self.integration_night
        else:
            logger.info('Switching TSL2591 to day mode - Gain %d, Integration: %d', self.gain_day, self.integration_day)
            self.tsl2591.gain = self.gain_day
            self.tsl2591.integration_time = self.integration_day

        time.sleep(1.0)


### exceptions
class DeviceControlException(Exception):
    pass


class SensorReadException(Exception):
    pass


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'sensor',
        help='sensor',
        choices=(
            'bmp180_i2c',
            'bmp280_i2c',
            'bme280_i2c',
            'bme680_i2c',
            'ahtx0_i2c',
            'tsl2591_i2c',
        ),
    )
    argparser.add_argument(
        '--i2c_address',
        '-i',
        help='Sensor I2C address (example: 0x20)',
        type=str,
        default='0x20',
    )

    args = argparser.parse_args()


    if args.sensor == 'bmp180_i2c':
        mqs_class = MqttRemoteSensorBmp180_I2C
    elif args.sensor == 'bmp280_i2c':
        mqs_class = MqttRemoteSensorBmp280_I2C
    elif args.sensor == 'bme280_i2c':
        mqs_class = MqttRemoteSensorBme280_I2C
    elif args.sensor == 'bme680_i2c':
        mqs_class = MqttRemoteSensorBme680_I2C
    elif args.sensor == 'ahtx0_i2c':
        mqs_class = MqttRemoteSensorAhtx0_I2C
    elif args.sensor == 'tsl2591_i2c':
        mqs_class = MqttRemoteSensorTsl2591_I2C


    mqs = mqs_class()
    mqs.i2c_address = args.i2c_address


    mqs.run()
