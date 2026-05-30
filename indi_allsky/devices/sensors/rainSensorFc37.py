import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorException

logger = logging.getLogger('indi_allsky')


class RainSensorFc37(SensorBase):

    METADATA = {
        'name': 'FC-37 Rain Sensor',
        'description': 'FC-37 Rain Detection Sensor (digital output)',
        'count': 1,
        'labels': (
            'Rain Detection',
        ),
        'types': (
            constants.SENSOR_PRECIPITATION,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(RainSensorFc37, self).__init__(*args, **kwargs)

        pin_1_name = kwargs.get('pin_1_name')
        if not pin_1_name:
            raise SensorException('FC-37 sensor pin not configured (TEMP_SENSOR.__*_PIN_1)')

        try:
            import board
            import digitalio
        except Exception as e:
            raise SensorException('FC-37 sensor requires board/digitalio support: %s' % str(e)) from e

        if not hasattr(board, pin_1_name):
            raise SensorException('FC-37 sensor pin name "%s" is not valid' % pin_1_name)

        self.sensor_pin = digitalio.DigitalInOut(getattr(board, pin_1_name))
        self.sensor_pin.direction = digitalio.Direction.INPUT
        self.sensor_pin.pull = digitalio.Pull.UP

        self.active_low = bool(
            self.config.get('TEMP_SENSOR', {}).get('FC37_ACTIVE_LOW', True)
        )

        logger.warning('[%s] Initialized FC-37 rain sensor on pin %s, active_low=%s', self.name, pin_1_name, self.active_low)


    def update(self):
        try:
            raw_value = self.sensor_pin.value
        except Exception as e:
            raise SensorException('FC-37 sensor read failure: %s' % str(e)) from e

        # FC-37 TFT digital output is typically low when water is detected.
        detected = (not raw_value) if self.active_low else raw_value


        # 0 = No Rain
        # 1 = Raining
        rain_value = 1 if detected else 0


        rain_state = constants.RAIN_MAP_STR[rain_value]
        logger.info('[%s] FC-37 rain sensor: %s (%s)', self.name, rain_state, rain_value)

        return {
            'rain' : rain_value,
            'data': (),
        }


    def deinit(self):
        try:
            self.sensor_pin.deinit()
        except Exception:
            pass
