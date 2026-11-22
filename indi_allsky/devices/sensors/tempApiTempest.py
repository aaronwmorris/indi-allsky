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


class _TempestSensorBase(SensorBase):
    """Shared metadata, unit conversions, and payload builder for Tempest sensors."""

    METADATA = {
        'name' : 'Tempest Weather API',
        'description' : 'WeatherFlow Tempest REST API Sensor',
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
            'Illuminance',
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
            constants.SENSOR_LIGHT_LUX,
        ),
    }

    def _convert_temperature(self, temp_c, mode):
        if mode == 'f':
            return self.c2f(temp_c)
        if mode == 'k':
            return self.c2k(temp_c)
        return temp_c

    def _convert_wind_speed(self, speed_mps, mode):
        if mode == 'mph':
            return self.mps2miph(speed_mps)
        if mode == 'knots':
            return self.mps2knots(speed_mps)
        if mode == 'kph':
            return self.mps2kmph(speed_mps)
        return speed_mps

    def _convert_pressure(self, pressure_hpa, mode):
        if mode == 'psi':
            return self.hPa2psi(pressure_hpa)
        if mode == 'inHg':
            return self.hPa2inHg(pressure_hpa)
        if mode == 'mmHg':
            return self.hPa2mmHg(pressure_hpa)
        return pressure_hpa

    def _build_data(
        self,
        temp_c,
        rel_h,
        pressure_hpa,
        wind_speed,
        wind_gust,
        wind_deg,
        rain_1h,
        solar_radiation,
        uv,
        illuminance,
        feels_like_c=None,
    ):
        if feels_like_c is None:
            feels_like_c = temp_c

        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0

        heat_index_c = self.get_heat_index_c(temp_c, rel_h)

        temp_display = self.config.get('TEMP_DISPLAY')
        current_temp = self._convert_temperature(temp_c, temp_display)
        current_feels_like = self._convert_temperature(feels_like_c, temp_display)
        current_dp = self._convert_temperature(dew_point_c, temp_display)
        current_fp = self._convert_temperature(frost_point_c, temp_display)
        current_hi = self._convert_temperature(heat_index_c, temp_display)
        current_rain_1h = self.mm2in(rain_1h) if temp_display == 'f' else rain_1h

        wind_display = self.config.get('WINDSPEED_DISPLAY')
        current_wind_speed = self._convert_wind_speed(wind_speed, wind_display)
        current_wind_gust = self._convert_wind_speed(wind_gust, wind_display)

        pressure_display = self.config.get('PRESSURE_DISPLAY')
        current_pressure = self._convert_pressure(pressure_hpa, pressure_display)

        return {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'wind_degrees' : wind_deg,
            'data' : (
                current_temp,
                current_feels_like,
                rel_h,
                current_pressure,
                current_wind_speed,
                current_wind_gust,
                current_rain_1h,
                solar_radiation,
                uv,
                illuminance,
            ),
        }


class TempApiTempest(_TempestSensorBase):
    """WeatherFlow Tempest REST API sensor using Personal Access Token (PAT) auth."""

    BASE_URL = 'https://swd.weatherflow.com/swd/rest'


    def __init__(self, *args, **kwargs):
        super(TempApiTempest, self).__init__(*args, **kwargs)

        logger.warning('Initializing [%s] Tempest Weather API Sensor', self.name)

        temp_sensor_conf = self.config.get('TEMP_SENSOR', {})
        self.token = str(temp_sensor_conf.get('TEMPEST_APIKEY', '')).strip()
        if not self.token:
            raise Exception('Tempest Personal Access Token is empty')

        station_id = str(temp_sensor_conf.get('TEMPEST_STATION_ID', '')).strip()
        self.station_id = station_id if station_id else None

        self.data = {
            'data' : tuple(),
        }

        self.next_run = time.time()  # run immediately
        self.next_run_offset = 300  # five minutes


    def _get_json(self, path):
        url = f'{self.BASE_URL}{path}'
        try:
            r = requests.get(
                url,
                params={'token': self.token},
                verify=True,
                timeout=(5.0, 10.0),
            )
        except (
            socket.gaierror,
            socket.timeout,
            requests.exceptions.RequestException,
            ssl.SSLCertVerificationError,
        ) as e:
            raise SensorReadException(str(e)) from e

        if r.status_code >= 400:
            raise SensorReadException('Tempest API returned {0:d}'.format(r.status_code))

        try:
            r_data = r.json()
        except json.JSONDecodeError as e:
            raise SensorReadException(str(e)) from e

        status = r_data.get('status') or {}
        if status.get('status_code', 0) != 0:
            raise SensorReadException(
                'Tempest API error {0}: {1}'.format(
                    status.get('status_code'),
                    status.get('status_message', 'Unknown error'),
                )
            )

        return r_data


    def _resolve_station_id(self):
        r_data = self._get_json('/stations')
        stations = r_data.get('stations') or []
        if not stations:
            raise SensorReadException('No Tempest stations found for token')

        station_id = stations[0].get('station_id')
        if station_id is None:
            raise SensorReadException('Tempest station response missing station_id')

        return str(station_id)


    def update(self):
        now = time.time()
        if now < self.next_run:
            return self.data

        self.next_run = now + self.next_run_offset

        if not self.station_id:
            self.station_id = self._resolve_station_id()

        r_data = self._get_json(f'/observations/station/{self.station_id}')
        obs_list = r_data.get('obs') or []
        if not obs_list:
            raise SensorReadException('No observations returned by Tempest API')

        obs = obs_list[0]

        # Tempest REST station observations are always returned in metric units
        temp_c = float(obs.get('air_temperature') or 0.0)
        feels_like_raw = obs.get('feels_like')
        feels_like_c = float(feels_like_raw) if feels_like_raw is not None else temp_c
        rel_h = float(obs.get('relative_humidity') or 0.0)

        pressure_raw = obs.get('barometric_pressure')
        if pressure_raw is None:
            pressure_raw = obs.get('station_pressure')
        pressure_hpa = float(pressure_raw or 0.0)

        wind_avg_raw = obs.get('wind_avg')
        if wind_avg_raw is None:
            wind_avg_raw = obs.get('wind_speed')
        wind_speed = float(wind_avg_raw or 0.0)
        wind_gust = float(obs.get('wind_gust') or 0.0)
        wind_deg = float(obs.get('wind_direction') or 0.0)

        rain_raw = obs.get('precip_accum_last_1hr')
        if rain_raw is None:
            rain_raw = obs.get('precip')
        rain_1h = float(rain_raw or 0.0)

        solar_radiation = float(obs.get('solar_radiation') or 0.0)
        uv = float(obs.get('uv') or 0.0)
        illuminance = float(obs.get('brightness') or 0.0)

        logger.info(
            '[%s] Tempest API - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa',
            self.name,
            temp_c,
            rel_h,
            pressure_hpa,
        )

        self.data = self._build_data(
            temp_c=temp_c,
            rel_h=rel_h,
            pressure_hpa=pressure_hpa,
            wind_speed=wind_speed,
            wind_gust=wind_gust,
            wind_deg=wind_deg,
            rain_1h=rain_1h,
            solar_radiation=solar_radiation,
            uv=uv,
            illuminance=illuminance,
            feels_like_c=feels_like_c,
        )

        return self.data
