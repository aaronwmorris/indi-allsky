#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorBh1750(SensorBase):

    def update(self):

        try:
            lux = float(self.bh1750.lux)  # can be None
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] BH1750 - lux: %0.4f', self.name, lux)


        astro_darkness = self.astro_av[constants.ASTRO_SUN_ALT] <= 18.0
        if astro_darkness:
            try:
                sqm_mag, raw_mag = self.lux2mag(lux)
            except ValueError as e:
                logger.error('SQM calculation error - ValueError: %s', str(e))
                sqm_mag = 0.0
                raw_mag = 0.0
        else:
            sqm_mag = 0.0
            raw_mag = 0.0


        data = {
            'sqm_mag' : sqm_mag,
            'data' : (
                lux,
                sqm_mag,
                raw_mag,
            ),
        }

        return data


class LightSensorBh1750_I2C(LightSensorBh1750):

    METADATA = {
        'name' : 'BH1750 (i2c)',
        'description' : 'BH1750 i2c Light Sensor',
        'count' : 3,
        'labels' : (
            'Lux',
            'SQM',
            'Raw Magnitude',
        ),
        'types' : (
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorBh1750_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_bh1750

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] BH1750 I2C light sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.bh1750 = adafruit_bh1750.BH1750(i2c, address=i2c_address)


