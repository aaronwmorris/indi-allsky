import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorScd4x(SensorBase):

    def update(self):

        if not self.scd4x.data_ready:
            logger.warning('SCD-4x data not available')
            return self.data


        try:
            temp_c = float(self.scd4x.temperature)
            rel_h = float(self.scd4x.relative_humidity)
            CO2 = float(self.scd4x.CO2)  # ppm
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SCD-4x - temp: %0.1fc, humidity: %0.1f%%, CO2: %0.1fppm', self.name, temp_c, rel_h, CO2)


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


        self.data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'data' : (
                current_temp,
                rel_h,
                CO2,
                current_dp,
            ),
        }

        return self.data


class TempSensorScd4x_I2C(TempSensorScd4x):

    METADATA = {
        'name' : 'SCD-4x',
        'description' : 'SCD-4x i2c Temperature Sensor',
        'count' : 4,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'CO2 (ppm)',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_CONCENTRATION,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorScd4x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_scd4x

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SCD-4x I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.scd4x = adafruit_scd4x.SCD4x(i2c, address=i2c_address)

        self.scd4x.start_periodic_measurement()

        time.sleep(1)  # allow things to settle

        self.data = {
            'data' : tuple(),
        }

