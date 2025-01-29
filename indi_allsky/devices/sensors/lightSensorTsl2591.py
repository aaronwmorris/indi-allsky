import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2591(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        #gain = self.tsl2591.gain
        #integration = self.tsl2591.integration_time
        #logger.info('[%s] TSL2591 settings - Gain: %d, Integration: %d', gain, integration)


        try:
            lux = float(self.tsl2591.lux)
            infrared = int(self.tsl2591.infrared)
            visible = int(self.tsl2591.visible)
            full_spectrum = int(self.tsl2591.full_spectrum)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] TSL2591 - lux: %0.4f, visible: %d, ir: %d, full: %d', self.name, lux, visible, infrared, full_spectrum)


        try:
            sqm_mag = self.lux2mag(lux)
        except ValueError as e:
            logger.error('SQM calculation error - ValueError: %s', str(e))
            sqm_mag = 0.0


        data = {
            'sqm_mag' : sqm_mag,
            'data' : (
                lux,
                visible,
                infrared,
                full_spectrum,
            ),
        }

        return data


    def update_sensor_settings(self):
        if self.night:
            logger.info('[%s] Switching TSL2591 to night mode - Gain %d, Integration: %d', self.name, self.gain_night, self.integration_night)
            self.tsl2591.gain = self.gain_night
            self.tsl2591.integration_time = self.integration_night
        else:
            logger.info('[%s] Switching TSL2591 to day mode - Gain %d, Integration: %d', self.name, self.gain_day, self.integration_day)
            self.tsl2591.gain = self.gain_day
            self.tsl2591.integration_time = self.integration_day

        time.sleep(1.0)



class LightSensorTsl2591_I2C(LightSensorTsl2591):

    METADATA = {
        'name' : 'TSL2591 (i2c)',
        'description' : 'TSL2591 i2c Light Sensor',
        'count' : 4,
        'labels' : (
            'Lux',
            'Visible',
            'Infrared',
            'Full Spectrum',
        ),
        'types' : (
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorTsl2591_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_tsl2591

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] TSL2591 I2C light sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.tsl2591 = adafruit_tsl2591.TSL2591(i2c, address=i2c_address)

        self.gain_night = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_GAIN_NIGHT', 'GAIN_MED'))
        self.gain_day = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_GAIN_DAY', 'GAIN_LOW'))
        self.integration_night = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_INT_NIGHT', 'INTEGRATIONTIME_100MS'))
        self.integration_day = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_INT_DAY', 'INTEGRATIONTIME_100MS'))


        ### You can optionally change the gain and integration time:
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_LOW   # (1x gain)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_MED   # (25x gain, the default)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_HIGH  # (428x gain)
        #self.tsl2591.gain = adafruit_tsl2591.GAIN_MAX   # (9876x gain)

        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_100MS  # (100ms, default)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_200MS  # (200ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_300MS  # (300ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_400MS  # (400ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_500MS  # (500ms)
        #self.tsl2591.integration_time = adafruit_tsl2591.INTEGRATIONTIME_600MS  # (600ms)

        time.sleep(1)

