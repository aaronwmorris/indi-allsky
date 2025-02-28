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
#{'base': 'stations',
# 'clouds': {'all': 58},
# 'cod': 200,
# 'coord': {'lat': 33, 'lon': -84},
# 'dt': 1718044502,
# 'id': 4195771,
# 'main': {'feels_like': 33.49,
#          'grnd_level': 986,
#          'humidity': 58,
#          'pressure': 1009,
#          'sea_level': 1009,
#          'temp': 30.56,
#          'temp_max': 31.4,
#          'temp_min': 28.01},
# 'name': 'Forsyth',
# 'sys': {'country': 'US',
#         'id': 2010956,
#         'sunrise': 1718015218,
#         'sunset': 1718066661,
#         'type': 2},
# 'timezone': -14400,
# 'visibility': 10000,
# 'weather': [{'description': 'broken clouds',
#              'icon': '04d',
#              'id': 803,
#              'main': 'Clouds'}],
# 'wind': {'deg': 306, 'gust': 4.89, 'speed': 3.3}}
###


class TempApiOpenWeatherMap(SensorBase):

    UNITS = 'metric'
    URL_TEMPLATE = 'https://api.openweathermap.org/data/2.5/weather?lat={latitude:0.1f}&lon={longitude:0.1f}&units={units:s}&appid={apikey:s}'


    METADATA = {
        'name' : 'OpenWeatherMap API',
        'description' : 'OpenWeatherMap API Sensor',
        'count' : 10,
        'labels' : (
            'Temperature',
            'Feels Like Temperature',
            'Relative Humidity',
            'Pressure',
            'Clouds',
            'Wind Speed',
            'Wind Gusts',
            'Rain (1h)',
            'Snow (1h)',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
            constants.SENSOR_PERCENTAGE,
            constants.SENSOR_WIND_SPEED,
            constants.SENSOR_WIND_SPEED,
            constants.SENSOR_PRECIPITATION,
            constants.SENSOR_PRECIPITATION,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempApiOpenWeatherMap, self).__init__(*args, **kwargs)

        logger.warning('Initializing [%s] OpenWeather API Sensor', self.name)

        apikey = self.config.get('TEMP_SENSOR', {}).get('OPENWEATHERMAP_APIKEY', '')

        if not apikey:
            raise Exception('OpenWeatherMap API key is empty')


        latitude = self.config['LOCATION_LATITUDE']
        longitude = self.config['LOCATION_LONGITUDE']

        self.url = self.URL_TEMPLATE.format(**{
            'latitude'  : latitude,
            'longitude' : longitude,
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
            raise SensorReadException('OpenWeatherMap API returned {0:d}'.format(r.status_code))


        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            raise SensorReadException(str(e)) from e


        temp_c = float(r_data['main']['temp'])
        feels_like_c = float(r_data['main']['feels_like'])
        rel_h = int(r_data['main']['humidity'])
        pressure_hpa = int(r_data['main']['pressure'])
        clouds_percent = int(r_data['clouds']['all'])


        wind = r_data.get('wind', {})
        if wind:
            wind_deg = int(wind.get('deg', 0))
            wind_speed = float(wind.get('speed', 0.0))
            wind_gust = float(wind.get('gust', 0.0))
        else:
            wind_deg = 0.0
            wind_speed = 0.0  # meters/s
            wind_gust = 0.0  # meters/s


        rain = r_data.get('rain', {})
        if rain:
            rain_1h = float(rain.get('1h', 0.0))  # mm
            #rain_3h = float(rain.get('3h', 0.0))  # mm
        else:
            rain_1h = 0.0
            #rain_3h = 0.0


        snow = r_data.get('snow', {})
        if snow:
            snow_1h = float(snow.get('1h', 0.0))  # mm
            #snow_3h = float(snow.get('3h', 0.0))  # mm
        else:
            snow_1h = 0.0
            #snow_3h = 0.0


        logger.info('[%s] OpenWeather API - temp: %0.1fc, humidity: %d%%, pressure: %0.1fhPa, clouds: %d%%', self.name, temp_c, rel_h, pressure_hpa, clouds_percent)


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
            current_feels_like = self.c2f(feels_like_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)

            ### assume inches if you are showing F
            current_rain_1h = self.mm2in(rain_1h)
            #current_rain_3h = self.mm2in(rain_3h)
            current_snow_1h = self.mm2in(snow_1h)
            #current_snow_3h = self.mm2in(snow_3h)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            current_feels_like = self.c2k(feels_like_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
            current_rain_1h = rain_1h
            #current_rain_3h = rain_3h
            current_snow_1h = snow_1h
            #current_snow_3h = snow_3h
        else:
            current_temp = temp_c
            current_feels_like = feels_like_c
            current_dp = dew_point_c
            current_fp = frost_point_c
            current_hi = heat_index_c
            current_rain_1h = rain_1h
            #current_rain_3h = rain_3h
            current_snow_1h = snow_1h
            #current_snow_3h = snow_3h


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
            current_pressure = self.hPa2psi(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        self.data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'wind_degrees' : wind_deg,
            'data' : (
                current_temp,
                current_feels_like,
                rel_h,
                current_pressure,
                clouds_percent,
                current_wind_speed,
                current_wind_gust,
                current_rain_1h,
                current_snow_1h,
                current_dp,
            ),
        }

        return self.data


