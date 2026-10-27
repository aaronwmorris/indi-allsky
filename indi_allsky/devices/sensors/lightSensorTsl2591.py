import math
import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2591(SensorBase):

    def __init__(self, *args, **kwargs):
        super(LightSensorTsl2591, self).__init__(*args, **kwargs)
        self._clipped = False


    def update(self):
        astro_darkness = self.astro_av[constants.ASTRO_SUN_ALT] <= -18.0
        if self.astro_darkness != astro_darkness:
            self.astro_darkness = astro_darkness
            self.update_sensor_settings()


        #gain = self.tsl2591.gain
        #integration = self.tsl2591.integration_time
        #logger.info('[%s] TSL2591 settings - Gain: %d, Integration: %d', gain, integration)


        if self.disable_day:
            data = {
                'data' : (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            }

            return data


        try:
            raw_lux = self.tsl2591.lux
        except RuntimeError as e:
            if 'overflow' in str(e).lower():
                raw_lux = None
            else:
                raise SensorReadException(str(e)) from e
        except (TypeError, OSError):
            raw_lux = None

        try:
            infrared = int(self.tsl2591.infrared) if self.tsl2591.infrared is not None else float('nan')
            visible = int(self.tsl2591.visible) if self.tsl2591.visible is not None else float('nan')
            full_spectrum = int(self.tsl2591.full_spectrum) if self.tsl2591.full_spectrum is not None else float('nan')
        except (RuntimeError, OSError) as e:
            raise SensorReadException(str(e)) from e
        except Exception:
            infrared = float('nan')
            visible = float('nan')
            full_spectrum = float('nan')

        if raw_lux is None:
            if not self._clipped:
                logger.warning('[%s] TSL2591 sensor clipped or out of range (lux is None)', self.name)
                self._clipped = True
            lux = float('nan')
        else:
            if self._clipped:
                logger.info('[%s] TSL2591 sensor returned to valid range (lux: %0.4f)', self.name, float(raw_lux))
                self._clipped = False
            lux = float(raw_lux)


        if math.isnan(lux):
            logger.debug('[%s] TSL2591 - lux: out of range, visible: %s, ir: %s, full: %s', self.name, visible, infrared, full_spectrum)
        else:
            logger.info('[%s] TSL2591 - lux: %0.4f, visible: %s, ir: %s, full: %s', self.name, lux, visible, infrared, full_spectrum)


        if self.astro_darkness and not math.isnan(lux) and lux > 0:
            try:
                sqm_mag, raw_mag = self.lux2mag(lux)
            except ValueError as e:
                logger.error('SQM calculation error - ValueError: %s', str(e))
                sqm_mag = 0.0
                raw_mag = 0.0
        else:
            # disabled outside astronomical darkness or when lux is invalid
            sqm_mag = float('nan') if math.isnan(lux) else 0.0
            raw_mag = float('nan') if math.isnan(lux) else 0.0


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

