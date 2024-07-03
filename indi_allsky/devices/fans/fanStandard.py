import time
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanStandard(FanBase):

    def __init__(self, *args, **kwargs):
        super(FanStandard, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        import digitalio

        logger.info('Initializing standard FAN device')

        pin1 = getattr(board, pin_1_name)

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT


        if not invert_output:
            self.ON = 1
            self.OFF = 0
        else:
            self.ON = 0
            self.OFF = 1


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
            logger.warning('Set fan state: 100%')
            self.pin.value = self.ON
            self._state = 100
        else:
            logger.warning('Set fan state: 0%')
            self.pin.value = self.OFF
            self._state = 0


    def disable(self):
        self.state = 0

