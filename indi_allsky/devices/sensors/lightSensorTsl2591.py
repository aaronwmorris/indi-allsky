import logging

from .sensorBase import SensorBase
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2591(SensorBase):

    def update(self):

        try:
            lux = int(self.tsl2591.lux)
            infrared = int(self.tsl2591.infrared)
            visible = int(self.tsl2591.visible)
            full_spectrum = int(self.tsl2591.full_spectrum)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('TSL2591 - lux: %d, visible: %d, ir: %d, full: %d', lux, infrared, visible, full_spectrum)


        data = {
            'data' : (lux, visible, infrared, full_spectrum),
        }

        return data


class LightSensorTsl2591_I2C(LightSensorTsl2591):

    def __init__(self, *args, **kwargs):
        super(LightSensorTsl2591_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_tsl2591

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing TSL2591 I2C light sensor device @ %s', hex(i2c_address))
        i2c = board.I2C()
        self.tsl2591 = adafruit_tsl2591.TSL2591(i2c, address=i2c_address)


        # You can optionally change the gain and integration time:
        # self.tsl2591.gain = adafruit_tsl2591.GAIN_LOW (1x gain)
        # self.tsl2591.gain = adafruit_tsl2591.GAIN_MED (25x gain, the default)
        # self.tsl2591.gain = adafruit_tsl2591.GAIN_HIGH (428x gain)
        # self.tsl2591.gain = adafruit_tsl2591.GAIN_MAX (9876x gain)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_100MS (100ms, default)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_200MS (200ms)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_300MS (300ms)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_400MS (400ms)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_500MS (500ms)
        # self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_600MS (600ms)

