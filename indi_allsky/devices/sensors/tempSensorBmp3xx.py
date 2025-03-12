import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBmp3xx(SensorBase):

    def update(self):

        try:
            temp_c = float(self.bmp3xx.temperature)
            pressure_hpa = float(self.bmp3xx.pressure)  # hPa
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] BMP3xx - temp: %0.1fc, pressure: %0.1fhPa', self.name, temp_c, pressure_hpa)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        if self.config.get('PRESSURE_DISPLAY') == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'data' : (
                current_temp,
                current_pressure,
            ),
        }

        return data


class TempSensorBmp3xx_I2C(TempSensorBmp3xx):

    METADATA = {
        'name' : 'BMP3xx (i2c)',
        'description' : 'BMP3xx i2c Temperature Sensor',
        'count' : 2,
        'labels' : (
            'Temperature',
            'Pressure',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorBmp3xx_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_bmp3xx

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] BMP3xx I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.bmp3xx = adafruit_bmp3xx.BMP3XX_I2C(i2c, address=i2c_address)


        self.bmp3xx.pressure_oversample = 8
        self.bmp3xx.temperature_oversample = 2


        # throw away, initial humidity reading is always 100%
        self.bmp3xx.temperature
        self.bmp3xx.pressure

        time.sleep(1)  # allow things to settle


class TempSensorBmp3xx_SPI(TempSensorBmp3xx):

    METADATA = {
        'name' : 'BMP3xx (SPI)',
        'description' : 'BMP3xx SPI Temperature Sensor',
        'count' : 2,
        'labels' : (
            'Temperature',
            'Pressure',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorBmp3xx_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import digitalio
        import adafruit_bmp3xx

        pin1 = getattr(board, pin_1_name)
        cs = digitalio.DigitalInOut(pin1)

        logger.warning('Initializing [%s] BMP3xx SPI temperature device', self.name)
        spi = board.SPI()
        self.bmp3xx = adafruit_bmp3xx.BMP3xx_SPI(spi, cs)


        self.bmp3xx.pressure_oversample = 8
        self.bmp3xx.temperature_oversample = 2


        # throw away, initial humidity reading is always 100%
        self.bmp3xx.temperature
        self.bmp3xx.pressure

        time.sleep(1)  # allow things to settle

