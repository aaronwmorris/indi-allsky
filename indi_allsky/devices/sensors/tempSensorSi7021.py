import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorSi7021(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        try:
            temp_c = float(self.si7021.temperature)
            rel_h = float(self.si7021.relative_humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] Si7021 - temp: %0.1fc, humidity: %0.1f%%', self.name, temp_c, rel_h)


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
            if self.heater_level_night >= 0:
                logger.info('[%s] Switching SI7021 to night mode - Heater level %d', self.name, self.heater_level_night)
                self.si7021.heater_enable = True
                self.si7021.heater_level = self.heater_level_day
            else:
                logger.info('[%s] Switching SI7021 to night mode - Heater OFF', self.name)
                self.si7021.heater_enable = False
        else:
            if self.heater_level_day >= 0:
                logger.info('[%s] Switching SI7021 to day mode - Heater level %d', self.name, self.heater_level_day)
                self.si7021.heater_enable = True
                self.si7021.heater_level = self.heater_level_day
            else:
                logger.info('[%s] Switching SI7021 to day mode - Heater OFF', self.name)
                self.si7021.heater_enable = False

        time.sleep(1.0)



class TempSensorSi7021_I2C(TempSensorSi7021):

    METADATA = {
        'name' : 'SI7021 (i2c)',
        'description' : 'SI7021 i2c Temperature Sensor',
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
        super(TempSensorSi7021_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_si7021

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] Si7021 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.si7021 = adafruit_si7021.SI7021(i2c, address=i2c_address)


        self.heater_level_night = int(self.config.get('TEMP_SENSOR', {}).get('SI7021_HEATER_LEVEL_NIGHT', -1))
        self.heater_level_day = int(self.config.get('TEMP_SENSOR', {}).get('SI7021_HEATER_LEVEL_DAY', -1))


        #self.si7021.heater_enable = True
        #self.si7021.heater_level = 0  # Use any level from 0 to 15 inclusive


        # The heater level of the integrated resistive heating element.  Per
        # the data sheet, the levels correspond to the following current draws:

        # ============  =================
        # Heater Level  Current Draw (mA)
        # ============  =================
        # 0             3.09
        # 1             9.18
        # 2             15.24
        # .             .
        # 4             27.39
        # .             .
        # 8             51.69
        # .             .
        # 15            94.20
        # ============  =================


