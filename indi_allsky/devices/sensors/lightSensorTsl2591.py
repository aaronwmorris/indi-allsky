import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2591(SensorBase):

    def update(self):
        astro_darkness = self.astro_av[constants.ASTRO_SUN_ALT] <= -18.0
        if self.astro_darkness != astro_darkness:
            self.astro_darkness = astro_darkness
            self.update_sensor_settings()


        #gain = self.tsl2591.gain
        #integration = self.tsl2591.integration_time
        #logger.info('[%s] TSL2591 settings - Gain: %d, Integration: %d', gain, integration)


        if self.disable_day and not self.astro_darkness:
            data = {
                'sample_disabled': True,
                'data' : (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            }

            return data


        lux, visible, infrared, full_spectrum = self.read_channels()


        logger.info('[%s] TSL2591 - lux: %0.4f, visible: %d, ir: %d, full: %d', self.name, lux, visible, infrared, full_spectrum)


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
                lux,
                visible,
                infrared,
                full_spectrum,
                sqm_mag,
                raw_mag,
            ),
        }

        return data


    def read_channels(self):
        # Keep the configured day/night gain as the ceiling. A bright light or
        # the Moon may saturate the ADC even during astronomical darkness.
        sensor = self.tsl2591
        target = self.gain_night if self.astro_darkness else self.gain_day
        idx = self.gain_levels.index(sensor.gain)
        while True:
            try:
                lux = float(sensor.lux)
                infrared = int(sensor.infrared)
                visible = int(sensor.visible)
                full = int(sensor.full_spectrum)
                break
            except RuntimeError as e:
                if idx == 0 or 'overflow' not in str(e).lower():
                    raise SensorReadException(str(e)) from e
                idx -= 1
                sensor.gain = self.gain_levels[idx]
                logger.warning('[%s] TSL2591 saturated; retrying at gain %d', self.name, sensor.gain)
                # Allow a complete new integration at the reduced gain.
                time.sleep(2 * (1 + sensor.integration_time) * 0.1)

        if idx < self.gain_levels.index(target):
            # full_spectrum packs both ADC channels. Only step back up when
            # both will remain well below clipping at the next gain.
            multipliers = (1, 25, 428, 9876)
            predicted = max(full & 0xffff, infrared) * multipliers[idx + 1] / multipliers[idx]
            if predicted < 16000:
                sensor.gain = self.gain_levels[idx + 1]
        return lux, visible, infrared, full


    def update_sensor_settings(self):
        if self.astro_darkness:
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
        'count' : 6,
        'labels' : (
            'Lux',
            'Visible',
            'Infrared',
            'Full Spectrum',
            'SQM',
            'Raw Magnitude',
        ),
        'types' : (
            constants.SENSOR_LIGHT_LUX,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorTsl2591_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_tsl2591

        self.gain_levels = (adafruit_tsl2591.GAIN_LOW, adafruit_tsl2591.GAIN_MED,
                            adafruit_tsl2591.GAIN_HIGH, adafruit_tsl2591.GAIN_MAX)

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] TSL2591 I2C light sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.tsl2591 = adafruit_tsl2591.TSL2591(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        self.gain_night = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_GAIN_NIGHT', 'GAIN_MED'))
        self.gain_day = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_GAIN_DAY', 'GAIN_LOW'))
        self.integration_night = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_INT_NIGHT', 'INTEGRATIONTIME_100MS'))
        self.integration_day = getattr(adafruit_tsl2591, self.config.get('TEMP_SENSOR', {}).get('TSL2591_INT_DAY', 'INTEGRATIONTIME_100MS'))
        self.disable_day = bool(self.config.get('TEMP_SENSOR', {}).get('TSL2591_DISABLE_DAY', False))

        if self.disable_day:
            logger.warning('TSL2591 daytime operation disabled')


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

