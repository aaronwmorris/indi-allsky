#import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterDigital(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterDigital, self).__init__(*args, **kwargs)

        import board
        import digitalio

        pin1 = getattr(board, self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined'))

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT

        self._state = None


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set dew heater state: 100%')
            self.pin.value = 1
            self._state = 100
        else:
            logger.warning('Set dew heater state: 0%')
            self.pin.value = 0
            self._state = 0


    def disable(self):
        self.state = 0

