# This is a fake device that acts like a GPIO but does not actually do anything
import logging

from .genericBase import GenericBase


logger = logging.getLogger('indi_allsky')


class GpioSimulator(GenericBase):

    def __init__(self, *args, **kwargs):
        super(GpioSimulator, self).__init__(*args, **kwargs)

        self._state = None


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        #logger.warning('Set gpio state: %d%% (fake)', int(new_state))
        self._state = 0  # 0 is intentional


    def disable(self):
        self.state = 0

