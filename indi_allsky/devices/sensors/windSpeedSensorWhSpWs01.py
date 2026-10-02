import logging
import time
from threading import Lock

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorException

logger = logging.getLogger('indi_allsky')


class WindSpeedSensorWhSpWs01(SensorBase):

    METADATA = {
        'name': 'WH-SP-WS01 Cup Anemometer',
        'description': 'WH-SP-WS01 cup anemometer (pulse output)',
        'count': 1,
        'labels': (
            'Wind Speed',
        ),
        'types': (
            constants.SENSOR_WIND_SPEED,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(WindSpeedSensorWhSpWs01, self).__init__(*args, **kwargs)

        pin_1_name = kwargs.get('pin_1_name')
        if not pin_1_name:
            raise SensorException('WH-SP-WS01 sensor pin not configured (TEMP_SENSOR.__*_PIN_1)')

        try:
            import board
            from gpiozero import Button
        except Exception as e:
            raise SensorException('WH-SP-WS01 sensor requires board/gpiozero support: %s' % str(e)) from e

        if not hasattr(board, pin_1_name):
            raise SensorException('WH-SP-WS01 sensor pin name "%s" is not valid' % pin_1_name)

        self._pulse_lock = Lock()
        self._pulse_count = 0
        self.last_update = time.monotonic()
        self.input_device = None

        try:
            self.input_device = Button(
                getattr(board, pin_1_name).id,
                pull_up=True,
                bounce_time=0.02,
            )
            self.input_device.when_pressed = self._count_pulse
        except Exception as e:
            self.deinit()
            raise SensorException('Unable to initialize WH-SP-WS01 sensor on pin %s: %s' % (pin_1_name, str(e))) from e

        logger.warning('[%s] Initialized WH-SP-WS01 cup anemometer on pin %s with pull-up', self.name, pin_1_name)


    def _count_pulse(self):
        with self._pulse_lock:
            self._pulse_count += 1


    def update(self):
        with self._pulse_lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            pulse_count = self._pulse_count
            self._pulse_count = 0

        if elapsed <= 0:
            wind_speed_mps = 0.0
        else:
            # WH-SP-WS01 output is 2.4 km/h for each pulse per second.
            wind_speed_mps = (pulse_count / elapsed) * (2.4 / 3.6)

        if self.config.get('WINDSPEED_DISPLAY') == 'mph':
            wind_speed = self.mps2miph(wind_speed_mps)
        elif self.config.get('WINDSPEED_DISPLAY') == 'knots':
            wind_speed = self.mps2knots(wind_speed_mps)
        elif self.config.get('WINDSPEED_DISPLAY') == 'kph':
            wind_speed = self.mps2kmph(wind_speed_mps)
        else:
            wind_speed = wind_speed_mps

        logger.info('[%s] WH-SP-WS01 wind speed: %0.1f (%d pulses in %0.3f seconds)', self.name, wind_speed, pulse_count, elapsed)

        return {
            'wind_speed': wind_speed,
            'data': (
                wind_speed,
            ),
        }


    def deinit(self):
        try:
            if self.input_device is not None:
                self.input_device.close()
        except Exception:
            pass