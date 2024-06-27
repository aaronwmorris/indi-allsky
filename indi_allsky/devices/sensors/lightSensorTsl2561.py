import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2561(SensorBase):

    METADATA = {
        'name' : 'TSL2561',
        'description' : 'TSL2561 Light Sensor',
        'count' : 3,
        'label' : (
            'Lux',
            'Broadband',
            'Infrared',
        ),
        'type' : (
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }

    def update(self):

        try:
            lux = float(self.tsl2561.lux)  # can be None
            broadband = int(self.tsl2561.broadband)
            infrared = int(self.tsl2561.infrared)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('TSL2561 - lux: %0.4f, broadband: %d, ir: %d', lux, broadband, infrared)


        try:
            sqm_mag = self.lux2mag(lux)
        except ValueError as e:
            logger.error('SQM calculation error - ValueError: %s', str(e))
            sqm_mag = 0.0


        data = {
            'sqm_mag' : sqm_mag,
            'data' : (
                lux,
                broadband,
                infrared,
            ),
        }

        return data


class LightSensorTsl2561_I2C(LightSensorTsl2561):

    def __init__(self, *args, **kwargs):
        super(LightSensorTsl2561_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import busio
        import adafruit_tsl2561

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing TSL2561 I2C light sensor device @ %s', hex(i2c_address))
        i2c = busio.I2C(board.SCL, board.SDA)
        self.tsl2561 = adafruit_tsl2561.TSL2561(i2c, address=i2c_address)

        # Enable the light sensor
        self.tsl2561.enabled = True
        time.sleep(1)

        # Set gain 0=1x, 1=16x
        self.tsl2561.gain = 0

        # Set integration time (0=13.7ms, 1=101ms, 2=402ms, or 3=manual)
        self.tsl2561.integration_time = 1

        time.sleep(1)
