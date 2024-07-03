import time
import logging

from .genericBase import GenericBase


logger = logging.getLogger('indi_allsky')


class GpioStandard(GenericBase):

    def __init__(self, *args, **kwargs):
        super(GpioStandard, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        import digitalio

        logger.info('Initializing standard GPIO device')

        pin1 = getattr(board, pin_1_name)

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT


        if not invert_output:
            self.ON = 1
            self.OFF = 0
            self.ON_LEVEL = 'high'
            self.OFF_LEVEL = 'low'
        else:
            self.ON = 0
            self.OFF = 1
            self.ON_LEVEL = 'low'
            self.OFF_LEVEL = 'high'


        self._state = None

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set GPIO state: ON (%s)', self.ON_LEVEL)
            self.pin.value = self.ON
            self._state = 1
        else:
            logger.warning('Set GPIO state: OFF (%s)', self.OFF_LEVEL)
            self.pin.value = self.OFF
            self._state = 0


    def disable(self):
        self.state = 0

