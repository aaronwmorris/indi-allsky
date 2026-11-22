import logging

from .genericBase import GenericBase
from ..openDrainMixin import OpenDrainPinMixin


logger = logging.getLogger('indi_allsky')


class GpioOpenDrain(OpenDrainPinMixin, GenericBase):

    def __init__(self, *args, **kwargs):
        super(GpioOpenDrain, self).__init__(*args, **kwargs)

        self._init_open_drain_pin(
            kwargs['pin_1_name'],
            kwargs['invert_output'],
            'GPIO',
        )
        self._state = -1

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        new_state_b = bool(new_state)
        self._set_open_drain_state(new_state_b)
        if new_state_b:
            logger.warning('Set GPIO open-drain state: ON')
            self._state = 1
        else:
            logger.warning('Set GPIO open-drain state: OFF')
            self._state = 0
