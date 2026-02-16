import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class LightSensorLtr390(SensorBase):

    def update(self):
        astro_darkness = self.astro_av[constants.ASTRO_SUN_ALT] <= 18.0
        if self.astro_darkness != astro_darkness:
            self.astro_darkness = astro_darkness
            self.update_sensor_settings()


        #gain = self.ltr390.gain
        #integration = self.ltr390.integration_time
        #logger.info('[%s] LTR390 settings - Gain: %d', gain)


        try:
            uvs = int(self.ltr390.uvs)
            light = int(self.ltr390.light)
            uvi = float(self.ltr390.uvi)
            lux = float(self.ltr390.lux)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] LTR390 - uv: %d, light: %d, uvi: %0.4f, lux: %0.4f', self.name, uvs, light, uvi, lux)


        if self.astro_darkness:
            try:
                sqm_mag, raw_mag = self.lux2mag(lux)
            except ValueError as e:
                logger.error('SQM calculation error - ValueError: %s', str(e))
                sqm_mag = 0.0
                raw_mag = 0.0
        else:
            # disabled outside astronomical darkness
            sqm_mag = 0.0
            raw_mag = 0.0


        data = {
            'sqm_mag' : sqm_mag,
            'data' : (
                uvs,
                light,
                uvi,
                lux,
                sqm_mag,
                raw_mag,
            ),
        }

        return data


    def update_sensor_settings(self):
        if self.astro_darkness:
            logger.info('[%s] Switching LTR390 to night mode - Gain %d', self.name, self.gain_night)
            self.ltr390.gain = self.gain_night
        else:
            logger.info('[%s] Switching LTR390 to day mode - Gain %d', self.name, self.gain_day)
            self.ltr390.gain = self.gain_day

        time.sleep(1.0)



class LightSensorLtr390_I2C(LightSensorLtr390):

    METADATA = {
        'name' : 'LTR390 (i2c)',
        'description' : 'LTR390 i2c UV Light Sensor',
        'count' : 6,
        'labels' : (
            'UV',
            'Light',
            'UV Index',
            'Lux',
            'SQM',
            'Raw Magnitude',
        ),
        'types' : (
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorLtr390_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_ltr390

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] LTR390 I2C light sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.ltr390 = adafruit_ltr390.LTR390(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.gain_night = getattr(adafruit_ltr390.Gain, self.config.get('TEMP_SENSOR', {}).get('LTR390_GAIN_NIGHT', 'GAIN_9X'))
        self.gain_day = getattr(adafruit_ltr390.Gain, self.config.get('TEMP_SENSOR', {}).get('LTR390_GAIN_DAY', 'GAIN_1X'))


        ### You can optionally change the gain
        #self.ltr390.gain = adafruit_ltr390.Gain.GAIN_1X
        #self.ltr390.gain = adafruit_ltr390.Gain.GAIN_3X
        #self.ltr390.gain = adafruit_ltr390.Gain.GAIN_6X
        #self.ltr390.gain = adafruit_ltr390.Gain.GAIN_9X
        #self.ltr390.gain = adafruit_ltr390.Gain.GAIN_18X

        time.sleep(1)

