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


class TempApiAmbientWeather(SensorBase):

    ### https://ambientweather.docs.apiary.io/#
    ###
    ### [ {
    ###   "dateutc": 1515436500000,
    ###   "date": "2018-01-08T18:35:00.000Z",
    ###   "winddir": 58,
    ###   "windspeedmph": 0.9,
    ###   "windgustmph": 4,
    ###   "maxdailygust": 5,
    ###   "windgustdir": 61,
    ###   "winddir_avg2m": 63,
    ###   "windspdmph_avg2m": 0.9,
    ###   "winddir_avg10m": 58,
    ###   "windspdmph_avg10m": 0.9,
    ###   "tempf": 66.9,
    ###   "humidity": 30,
    ###   "baromrelin": 30.05,
    ###   "baromabsin": 28.71,
    ###   "tempinf": 74.1,
    ###   "humidityin": 30,
    ###   "hourlyrainin": 0,
    ###   "dailyrainin": 0,
    ###   "monthlyrainin": 0,
    ###   "yearlyrainin": 0,
    ###   "feelsLike": 66.9,
    ###   "dewPoint": 34.45380707462477
    ### }, ... ]

    URL_TEMPLATE = 'https://rt.ambientweather.net/v1/devices/{macaddress:s}?apiKey={apikey:s}&applicationKey={applicationkey:s}&limit=288'


    METADATA = {
        'name' : 'Ambient Weather API',
        'description' : 'Ambient Weather Device API Sensor',
        'count' : 10,
        'labels' : (
            'Temperature',
            'Feels Like Temperature',
            'Relative Humidity',
            'Pressure',
            'Wind Speed',
            'Wind Gusts',
            '1 Hour Rain',
            'Solar Radiation',
            'UV',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
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
        super(TempApiAmbientWeather, self).__init__(*args, **kwargs)

        logger.warning('Initializing [%s] Ambient Weather API Sensor', self.name)

        apikey = self.config.get('TEMP_SENSOR', {}).get('AMBIENTWEATHER_APIKEY', '')
        applicationkey = self.config.get('TEMP_SENSOR', {}).get('AMBIENTWEATHER_APPLICATIONKEY', '')
        macaddress = self.config.get('TEMP_SENSOR', {}).get('AMBIENTWEATHER_MACADDRESS', '')

        if not apikey:
            raise Exception('Ambient Weather API key is empty')
        if not applicationkey:
            raise Exception('Ambient Weather Application key is empty')
        if not macaddress:
            raise Exception('Ambient Weather Device MAC address is empty')


        self.url = self.URL_TEMPLATE.format(**{
            'macaddress' : macaddress,
            'apikey'     : apikey,
            'applicationkey'    : applicationkey,
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
            raise SensorReadException('Ambient Weather API returned {0:d}'.format(r.status_code))


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            raise SensorReadException(str(e)) from e


        if r_data[0].get('tempf'):
            temp_f = float(r_data[0]['tempf'])
        else:
            temp_f = 0.0


        if r_data[0].get('dewPoint'):
            dewpt_f = float(r_data[0]['dewPoint'])
        else:
            dewpt_f = 0.0


        if r_data[0].get('feelsLike'):
            feels_like_f = float(r_data[0]['feelsLike'])
        else:
            feels_like_f = 0.0


        if r_data[0].get('humidity'):
            rel_h = float(r_data[0]['humidity'])
        else:
            rel_h = 0.0


        if r_data[0].get('baromrelin'):
            pressure_in = float(r_data[0]['baromrelin'])
        else:
            pressure_in = 0.0


        if r_data[0].get('windspeedmph'):
            wind_speed_mph = float(r_data[0]['windspeedmph'])
        else:
            wind_speed_mph = 0.0


        if r_data[0].get('windgustmph'):
            wind_gust_mph = float(r_data[0]['windgustmph'])
        else:
            wind_gust_mph = 0.0


        if r_data[0].get('winddir'):
            wind_dir = float(r_data[0]['winddir'])
        else:
            wind_dir = 0.0


        if r_data[0].get('hourlyrainin'):
            rain_total = float(r_data[0]['hourlyrainin'])
        else:
            rain_total = 0.0


        if r_data[0].get('solarradiation'):
            solar_radiation = float(r_data[0]['solarradiation'])
        else:
            solar_radiation = 0.0


        if r_data[0].get('uv'):
            uv = float(r_data[0]['uv'])
        else:
            uv = 0.0


        logger.info('[%s] Ambient Weather  API - temp: %0.1ff, feels like: %0.1ff humidity: %d%%', self.name, temp_f, feels_like_f, rel_h)


        dewpt_c = self.f2c(dewpt_f)


        try:
            dew_point_c = self.get_dew_point_c(self.f2c(temp_f), rel_h)
            frost_point_c = self.get_frost_point_c(self.f2c(temp_f), dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(self.f2c(temp_f), rel_h)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = temp_f
            current_dp = self.c2f(dew_point_c)
            current_dewpt = dewpt_f  # api
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
            current_fl = feels_like_f

            ### assume inches if you are showing F
            current_rain = rain_total
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.f2k(temp_f)
            current_dp = self.c2k(dew_point_c)
            current_dewpt = self.c2k(dewpt_c)  # api
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
            current_fl = self.f2k(feels_like_f)

            current_rain = rain_total
        else:
            current_temp = self.f2c(temp_f)
            current_dp = dew_point_c
            current_dewpt = dewpt_c  # api
            current_fp = frost_point_c
            current_hi = heat_index_c
            current_fl = self.f2c(feels_like_f)

            current_rain = rain_total


        if self.config.get('WINDSPEED_DISPLAY') == 'mph':
            current_wind_speed = wind_speed_mph
            current_wind_gust = wind_gust_mph
        elif self.config.get('WINDSPEED_DISPLAY') == 'knots':
            current_wind_speed = self.mph2knots(wind_speed_mph)
            current_wind_gust = self.mph2knots(wind_gust_mph)
        elif self.config.get('WINDSPEED_DISPLAY') == 'kph':
            current_wind_speed = self.mph2kmph(wind_speed_mph)
            current_wind_gust = self.mph2kmph(wind_gust_mph)
        else:
            # ms meters/s
            current_wind_speed = self.mph2mps(wind_speed_mph)
            current_wind_gust = self.mph2mps(wind_gust_mph)


        if self.config.get('PRESSURE_DISPLAY') == 'psi':
            current_pressure = self.inHg2psi(pressure_in)
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = pressure_in
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.inHg2mmHg(pressure_in)
        else:
            current_pressure = self.inHg2hpa(pressure_in)


        self.data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'wind_degrees' : wind_dir,
            'data' : (
                current_temp,
                current_fl,
                rel_h,
                current_pressure,
                current_wind_speed,
                current_wind_gust,
                current_rain,
                solar_radiation,
                uv,
                current_dewpt,  # api
            ),
        }

        return self.data


