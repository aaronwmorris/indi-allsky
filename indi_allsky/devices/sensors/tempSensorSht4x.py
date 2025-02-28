import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorSht4x(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        try:
            temp_c = float(self.sht4x.temperature)
            rel_h = float(self.sht4x.relative_humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SHT4x - temp: %0.1fc, humidity: %0.1f%%', self.name, temp_c, rel_h)


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
            logger.info('[%s] Switching SHT4X to night mode - Mode %s', self.name, hex(self.mode_night))
            self.sht4x.mode = self.mode_night
        else:
            logger.info('[%s] Switching SHT4X to day mode - Mode %s', self.name, hex(self.mode_day))
            self.sht4x.mode = self.mode_day

        time.sleep(1.0)


class TempSensorSht4x_I2C(TempSensorSht4x):

    METADATA = {
        'name' : 'SHT4x (i2c)',
        'description' : 'SHT4x i2c Temperature Sensor',
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
        super(TempSensorSht4x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_sht4x

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SHT4x I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.sht4x = adafruit_sht4x.SHT4x(i2c, address=i2c_address)

        self.mode_night = getattr(adafruit_sht4x.Mode, self.config.get('TEMP_SENSOR', {}).get('SHT4X_MODE_NIGHT', 'NOHEAT_HIGHPRECISION'))
        self.mode_day = getattr(adafruit_sht4x.Mode, self.config.get('TEMP_SENSOR', {}).get('SHT4X_MODE_DAY', 'NOHEAT_HIGHPRECISION'))


        # this should be the default
        #self.sht4x.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION

        # NOHEAT_HIGHPRECISION   No heater, high precision
        # NOHEAT_MEDPRECISION    No heater, med precision
        # NOHEAT_LOWPRECISION    No heater, low precision
        # HIGHHEAT_1S            High heat, 1 second
        # HIGHHEAT_100MS         High heat, 0.1 second
        # MEDHEAT_1S             Med heat, 1 second
        # MEDHEAT_100MS          Med heat, 0.1 second
        # LOWHEAT_1S             Low heat, 1 second
        # LOWHEAT_100MS          Low heat, 0.1 second

