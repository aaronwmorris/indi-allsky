import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorVeml7700(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        #gain = self.tsl2591.light_gain
        #integration = self.tsl2591.light_integration_time
        #logger.info('[%s] VEML7700 settings - Gain: %d, Integration: %d', gain, integration)


        try:
            lux = float(self.veml7700.lux)
            light = int(self.veml7700.light)
            white = int(self.veml7700.white)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] VEML770 - lux: %0.4f, light: %d, white: %d', self.name, lux, light, white)


        try:
            sqm_mag = self.lux2mag(lux)
        except ValueError as e:
            logger.error('SQM calculation error - ValueError: %s', str(e))
            sqm_mag = 0.0


        data = {
            'sqm_mag' : sqm_mag,
            'data' : (
                lux,
                light,
                white,
            ),
        }

        return data


    def update_sensor_settings(self):
        if self.night:
            logger.info('[%s] Switching VEML7700 to night mode - Gain: %d, Integration: %d', self.name, self.gain_night, self.integration_night)
            self.veml7700.light_gain = self.gain_night
            self.veml7700.light_integration_time = self.integration_night
        else:
            logger.info('[%s] Switching VEML7700 to day mode - Gain: %d, Integration: %d', self.name, self.gain_day, self.integration_day)
            self.veml7700.light_gain = self.gain_day
            self.veml7700.light_integration_time = self.integration_day

        time.sleep(1.0)


class LightSensorVeml7700_I2C(LightSensorVeml7700):

    METADATA = {
        'name' : 'VEML770 (i2c)',
        'description' : 'VEML7700 i2c Light Sensor',
        'count' : 3,
        'labels' : (
            'Lux',
            'Light',
            'White',
        ),
        'types' : (
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorVeml7700_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import busio
        import adafruit_veml7700

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] VEML7700 I2C light sensor device @ %s', self.name, hex(i2c_address))
        i2c = busio.I2C(board.SCL, board.SDA)
        self.veml7700 = adafruit_veml7700.VEML7700(i2c, address=i2c_address)

        self.gain_night = getattr(adafruit_veml7700.VEML7700, self.config.get('TEMP_SENSOR', {}).get('VEML7700_GAIN_NIGHT', 'ALS_GAIN_2'))
        self.gain_day = getattr(adafruit_veml7700.VEML7700, self.config.get('TEMP_SENSOR', {}).get('VEML7700_GAIN_DAY', 'ALS_GAIN_1_8'))
        self.integration_night = getattr(adafruit_veml7700.VEML7700, self.config.get('TEMP_SENSOR', {}).get('VEML7700_INT_NIGHT', 'ALS_100MS'))
        self.integration_day = getattr(adafruit_veml7700.VEML7700, self.config.get('TEMP_SENSOR', {}).get('VEML7700_INT_DAY', 'ALS_100MS'))


        time.sleep(1)

