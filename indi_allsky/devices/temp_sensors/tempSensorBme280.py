import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBme280(TempSensorBase):

    def update(self):

        try:
            temp_c = float(self.bme.temperature)
            rel_h = float(self.bme.humidity)
            pressure = float(self.bme.pressure)  # hPa
            #altitude = float(self.bme.altitude)  # meters
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        dew_point_c = self.get_dew_point_c(temp_c, rel_h)
        frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)


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


        logger.info('Temperature device: temp: %0.1f, humidity: %0.1f%%, pressure: %0.1f, dew pt: %0.1f, frost pt: %0.1f ', current_temp, rel_h, pressure, current_dp, current_fp)

        data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'data' : (current_temp, rel_h, pressure),
        }

        return data


class TempSensorBme280_I2C(TempSensorBme280):

    def __init__(self, *args, **kwargs):
        super(TempSensorBme280_I2C, self).__init__(*args, **kwargs)

        import board
        from adafruit_bme280 import basic as adafruit_bme280

        logger.warning('Initializing BME280 I2C temperature device')
        i2c = board.I2C()
        self.bme = adafruit_bme280.Adafruit_BME280_I2C(i2c)


class TempSensorBme280_SPI(TempSensorBme280):

    def __init__(self, *args, **kwargs):
        super(TempSensorBme280_SPI, self).__init__(*args, **kwargs)

        import board
        from adafruit_bme280 import basic as adafruit_bme280

        logger.warning('Initializing BME280 SPI temperature device')
        spi = board.SPI()
        self.bme = adafruit_bme280.Adafruit_BME280_SPI(spi)

