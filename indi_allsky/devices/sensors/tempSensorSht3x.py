import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorSht3x(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()

        try:
            temp_c = float(self.sht3x.temperature)
            rel_h = float(self.sht3x.relative_humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SHT3x - temp: %0.1fc, humidity: %0.1f%%', self.name, temp_c, rel_h)


        self.check_humidity_heater(rel_h)


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
            self.heater_available = self.heater_night
            self.heater_on = False
            self.sht3x.heater = False
        else:
            self.heater_available = self.heater_day
            self.heater_on = False
            self.sht3x.heater = False


    def check_humidity_heater(self, rh):
        if not self.heater_available:
            return


        if rh <= self.rh_heater_off_level:
            if self.heater_on:
                self.heater_on = False
                self.sht3x.heater = False
                logger.warning('[%s] SHT3X Heater Disabled')
                time.sleep(1.0)

        elif rh >= self.rh_heather_on_level:
            if not self.heater_on:
                self.heater_on = True
                self.sht3x.heater = True
                logger.warning('[%s] SHT3X Heater Enabled')
                time.sleep(1.0)


class TempSensorSht3x_I2C(TempSensorSht3x):

    METADATA = {
        'name' : 'SHT3x (i2c)',
        'description' : 'SHT3x i2c Temperature Sensor',
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
        super(TempSensorSht3x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_sht31d

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SHT3x I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.sht3x = adafruit_sht31d.SHT31D(i2c, address=i2c_address)

        self.heater_night = self.config.get('TEMP_SENSOR', {}).get('SHT3X_HEATER_NIGHT', False)
        self.heater_day = self.config.get('TEMP_SENSOR', {}).get('SHT3X_HEATER_DAY', False)


        # single shot data acquisition mode
        self.sht3x.mode = adafruit_sht31d.MODE_SINGLE

