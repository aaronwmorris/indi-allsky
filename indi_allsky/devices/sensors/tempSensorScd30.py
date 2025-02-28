import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorScd30(SensorBase):

    def update(self):

        if not self.scd30.data_available:
            logger.warning('SCD-30 data not available')
            return self.data


        try:
            temp_c = float(self.scd30.temperature)
            rel_h = float(self.scd30.relative_humidity)
            CO2 = float(self.scd30.CO2)  # ppm
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SCD-30 - temp: %0.1fc, humidity: %0.1f%%, CO2: %0.1fppm', self.name, temp_c, rel_h, CO2)


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


class TempSensorScd30_I2C(TempSensorScd30):

    METADATA = {
        'name' : 'SCD-30',
        'description' : 'SCD-30 i2c Temperature Sensor',
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
        super(TempSensorScd30_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import busio
        import adafruit_scd30

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SCD-30 I2C temperature device @ %s', self.name, hex(i2c_address))
        # SCD-30 has tempremental I2C with clock stretching, datasheet recommends
        # starting at 50KHz
        i2c = busio.I2C(board.SCL, board.SDA, frequency=50000)
        self.scd30 = adafruit_scd30.SCD30(i2c, address=i2c_address)

        time.sleep(1)  # allow things to settle

        self.data = {
            'data' : tuple(),
        }

