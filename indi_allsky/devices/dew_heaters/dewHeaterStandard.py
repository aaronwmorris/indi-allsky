import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterStandard(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterStandard, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        import digitalio

        logger.info('Initializing standard DEW HEATER device')

        pin1 = getattr(board, pin_1_name)

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT


        if invert_output:
            logger.warning('Dew heater logic reversed')
            self.ON = 0
            self.OFF = 1
        else:
            self.ON = 1
            self.OFF = 0


        self._state = -1

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set dew heater state: 100%')
            self.pin.value = self.ON
            self._state = 100
        else:
            logger.warning('Set dew heater state: 0%')
            self.pin.value = self.OFF
            self._state = 0


    def disable(self):
        self.state = 0


    def deinit(self):
        super(DewHeaterStandard, self).deinit()
        self.pin.deinit()

