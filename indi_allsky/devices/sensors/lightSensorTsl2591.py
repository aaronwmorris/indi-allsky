import time
import logging
import math

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class LightSensorTsl2591(SensorBase):

    def update(self):
        sun_alt = self.astro_av[constants.ASTRO_SUN_ALT]
        self.astro_darkness = sun_alt <= -18.0

        if self.disable_day and not self.astro_darkness:
            data = {
                'sample_disabled': True,
                'data' : (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            }

            return data


        lux, visible, infrared, full_spectrum = self.read_channels(sun_alt)


        logger.info('[%s] TSL2591 - lux: %0.4f, visible: %d, ir: %d, full: %d', self.name, lux, visible, infrared, full_spectrum)


        # The library's lux approximation can become negative under IR-heavy
        # light. Keep the raw channels usable and mark that measurement missing.
        if not math.isfinite(lux) or lux < 0:
            lux = None

        if self.astro_darkness and lux is not None and lux > 0:
            sqm_mag, raw_mag = self.lux2mag(lux)
        else:
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


    def exposure_settings(self, sun_alt):
        # Below the horizon, twilight may still need night sensitivity. Include
        # both profiles there and let the ADC counts determine the exposure.
        profiles = []
        if sun_alt < 0:
            profiles.append((self.gain_night, self.integration_night))
        if sun_alt > -18:
            profiles.append((self.gain_day, self.integration_day))

        settings = {(self.gain_levels[0], 0)}  # shortest exposure for sunlight
        for max_gain, integration in profiles:
            for gain in self.gain_levels[:self.gain_levels.index(max_gain) + 1]:
                settings.add((gain, integration))
        return sorted(settings, key=self.sensitivity)


    def sensitivity(self, setting):
        gain, integration = setting
        multiplier = (1, 25, 428, 9876)[self.gain_levels.index(gain)]
        return multiplier * (1 + integration)


    def read_channels(self, sun_alt):
        sensor = self.tsl2591
        settings = self.exposure_settings(sun_alt)
        current = (sensor.gain, sensor.integration_time)
        # Keep the previous working exposure across sunrise and twilight if
        # possible. On startup or a profile change, limit it to the new range.
        index = max(i for i, setting in enumerate(settings)
                    if self.sensitivity(setting) <= self.sensitivity(current))
        upper = len(settings) - 1
        while True:
            setting = settings[index]
            gain, integration = setting
            if setting != current:
                sensor.gain = gain
                sensor.integration_time = integration
                # An integration at the old setting may still be in flight.
                time.sleep(0.1 * (2 + current[1] + integration))
                current = setting

            limit = 36863 if integration == 0 else 65535
            try:
                lux = float(sensor.lux)
                broadband, infrared = sensor.raw_luminosity
                counts = max(broadband, infrared)
            except RuntimeError as e:
                if 'overflow' not in str(e).lower():
                    raise SensorReadException(str(e)) from e
                counts = limit

            if counts >= limit:
                if index == 0:
                    raise SensorReadException('TSL2591 saturated at minimum exposure')
                upper = index - 1
                index = upper
                continue

            # Allow ample headroom before increasing sensitivity. Read the
            # adjusted exposure in this poll, including when both ADCs are zero.
            # Never revisit a setting that already clipped during this poll.
            for next_index in range(upper, index, -1):
                candidate = settings[next_index]
                next_limit = 36863 if candidate[1] == 0 else 65535
                predicted = counts * self.sensitivity(candidate) / self.sensitivity(setting)
                if predicted < next_limit / 3:
                    index = next_index
                    break
            else:
                # Retain the installed library's public channel conventions.
                # Older releases include the IR high word in these two values.
                return lux, int(sensor.visible), int(infrared), int(sensor.full_spectrum)


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

