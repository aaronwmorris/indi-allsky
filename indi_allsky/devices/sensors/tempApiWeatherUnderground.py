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


### Example
###


class TempApiWeatherUnderground(SensorBase):

    ### https://www.ibm.com/docs/en/environmental-intel-suite?topic=apis-pws-observations-current-conditions

    UNITS = 's'  # s = metric_si
    #UNITS = 'm'  # m = metric

    URL_TEMPLATE = 'https://api.weather.com/v2/pws/observations/current?stationId={stationId:s}&format=json&numericPrecision=decimal&units={units:s}&apiKey={apikey:s}'


    METADATA = {
        'name' : 'Weather Underground API',
        'description' : 'Weather Underground API Sensor',
        'count' : 9,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Pressure',
            'Wind Speed',
            'Wind Gusts',
            'Total Precipitation',
            'Solar Radiation',
            'UV',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
            constants.SENSOR_WIND_SPEED,
            constants.SENSOR_WIND_SPEED,
            constants.SENSOR_PRECIPITATION,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempApiWeatherUnderground, self).__init__(*args, **kwargs)

        stationId = kwargs['pin_1_name']

        logger.warning('Initializing [%s] Weather Underground API Sensor', self.name)

        apikey = self.config.get('TEMP_SENSOR', {}).get('WUNDERGROUND_APIKEY', '')

        if not apikey:
            raise Exception('Weather Underground API key is empty')


        self.url = self.URL_TEMPLATE.format(**{
            'stationId' : stationId,
            'units'     : self.UNITS,
            'apikey'    : apikey,
        })

        self.data = {
            'data' : tuple(),
        }

        self.next_run = time.time()  # run immediately
        self.next_run_offset = 300  # five minutes


    def update(self):
        now = time.time()
        if now < self.next_run:
            # return cached data
            return self.data


        self.next_run = now + self.next_run_offset



        try:
            r = requests.get(self.url, verify=True, timeout=(5.0, 10.0))
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
            raise SensorReadException('Weather Underground API returned {0:d}'.format(r.status_code))


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            raise SensorReadException(str(e)) from e


        units = 'metric_si'
        #units = 'metric'

        if r_data['observations'][0][units].get('temp'):
            temp_c = float(r_data['observations'][0][units]['temp'])
        else:
            temp_c = 0.0


        if r_data['observations'][0].get('humidity'):
            rel_h = float(r_data['observations'][0]['humidity'])
        else:
            rel_h = 0.0


        if r_data['observations'][0][units].get('pressure'):
            pressure_mb = int(r_data['observations'][0][units]['pressure'])
        else:
            pressure_mb = 0


        if r_data['observations'][0][units].get('dewpt'):
            dewpt_c = float(r_data['observations'][0][units]['dewpt'])
        else:
            dewpt_c = 0.0


        if r_data['observations'][0].get('winddir'):
            wind_deg = int(r_data['observations'][0]['winddir'])
        else:
            wind_deg = 0

        if r_data['observations'][0][units].get('windSpeed'):
            wind_speed = float(r_data['observations'][0][units]['windSpeed'])
        else:
            wind_speed = 0.0

        if r_data['observations'][0][units].get('windGust'):
            wind_gust = float(r_data['observations'][0][units]['windGust'])
        else:
            wind_gust = 0.0


        if r_data['observations'][0][units].get('precipTotal'):
            rain_total = float(r_data['observations'][0][units]['precipTotal'])
        else:
            rain_total = 0.0


        if r_data['observations'][0].get('solarRadiation'):
            solar_radiation = float(r_data['observations'][0]['solarRadiation'])
        else:
            solar_radiation = 0.0

        if r_data['observations'][0].get('uv'):
            uv = float(r_data['observations'][0]['uv'])
        else:
            uv = 0.0



        logger.info('[%s] Weather Underground API - temp: %0.1fc, humidity: %d%%, pressure: %0.1fmb', self.name, temp_c, rel_h, pressure_mb)


        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(temp_c, rel_h)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_dewpt = self.c2f(dewpt_c)  # api measurement
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)

            ### assume inches if you are showing F
            current_rain = self.mm2in(rain_total)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_dewpt = self.c2k(dewpt_c)  # api measurement
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)

            current_rain = rain_total
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_dewpt = dewpt_c  # api measurement
            current_fp = frost_point_c
            current_hi = heat_index_c

            current_rain = rain_total


        if self.config.get('WINDSPEED_DISPLAY') == 'mph':
            current_wind_speed = self.mps2miph(wind_speed)
            current_wind_gust = self.mps2miph(wind_gust)
        elif self.config.get('WINDSPEED_DISPLAY') == 'knots':
            current_wind_speed = self.mps2knots(wind_speed)
            current_wind_gust = self.mps2knots(wind_gust)
        elif self.config.get('WINDSPEED_DISPLAY') == 'kph':
            current_wind_speed = self.mps2kmph(wind_speed)
            current_wind_gust = self.mps2kmph(wind_gust)
        else:
            # ms meters/s
            current_wind_speed = wind_speed
            current_wind_gust = wind_gust


        if self.config.get('PRESSURE_DISPLAY') == 'psi':
            current_pressure = self.hPa2psi(pressure_mb)  # 1 mb = 1 hPa
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = self.hPa2inHg(pressure_mb)  # 1 mb = 1 hPa
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_mb)  # 1 mb = 1 hPa
        else:
            current_pressure = pressure_mb


        self.data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'wind_degrees' : wind_deg,
            'data' : (
                current_temp,
                rel_h,
                current_pressure,
                current_wind_speed,
                current_wind_gust,
                current_rain,
                solar_radiation,
                uv,
                current_dewpt,  # api measurement
            ),
        }

        return self.data


