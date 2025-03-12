import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorHdc302x(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        try:
            temp_c = float(self.hdc302x.temperature)
            rel_h = float(self.hdc302x.relative_humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] HDC302x - temp: %0.1fc, humidity: %0.1f%%', self.name, temp_c, rel_h)


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
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
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
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'data' : (
                current_temp,
                rel_h,
                current_dp,
            ),
        }

        return data


    def update_sensor_settings(self):
        if self.night:
            logger.info('[%s] Switching HDC302x to night mode - Heater %s', self.name, self.heater_night)
            self.hdc302x.heater = self.heater_night
        else:
            logger.info('[%s] Switching HDC302x to day mode - Heater %s', self.name, self.heater_day)
            self.hdc302x.heater = self.heater_day

        time.sleep(1.0)


class TempSensorHdc302x_I2C(TempSensorHdc302x):

    METADATA = {
        'name' : 'HDC302x (i2c)',
        'description' : 'HDC302x i2c Temperature Sensor',
        'count' : 3,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorHdc302x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_hdc302x

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] HDC302x I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.hdc302x = adafruit_hdc302x.HDC302x(i2c, address=i2c_address)

        self.heater_night = self.config.get('TEMP_SENSOR', {}).get('HDC302X_HEATER_NIGHT', 'OFF')
        self.heater_day = self.config.get('TEMP_SENSOR', {}).get('HDC302X_HEATER_DAY', 'OFF')


        # this should be the default
        #self.hdc302x.heater = 'OFF'

        # OFF
        # QUARTER_POWER
        # HALF_POWER
        # FULL_POWER

