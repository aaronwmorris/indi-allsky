import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBmp180(TempSensorBase):

    def update(self):

        try:
            temp_c = float(self.bmp180.temperature)
            rel_h = float(self.bmp180.humidity)
            pressure = float(self.bmp180.pressure)  # hPa
            #altitude = float(self.bmp180.altitude)  # meters
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        logger.info('Temperature device: temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa', temp_c, rel_h, pressure)

        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c


        data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'data' : (current_temp, rel_h, pressure),
        }

        return data


class TempSensorBmp180_I2C(TempSensorBmp180):

    def __init__(self, *args, **kwargs):
        super(TempSensorBmp180_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import bmp180

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing BMP180 I2C temperature device @ %s', hex(i2c_address))
        i2c = board.I2C()
        self.bmp180 = bmp180.BMP180(i2c, address=i2c_address)

