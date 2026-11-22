import logging

from .fanBase import FanBase
from ..openDrainMixin import OpenDrainPinMixin


logger = logging.getLogger('indi_allsky')


class FanOpenDrain(OpenDrainPinMixin, FanBase):

    def __init__(self, *args, **kwargs):
        super(FanOpenDrain, self).__init__(*args, **kwargs)

        self._init_open_drain_pin(
            kwargs['pin_1_name'],
            kwargs['invert_output'],
            'FAN',
        )
        self._state = 0

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        new_state_b = bool(new_state)
        self._set_open_drain_state(new_state_b)
        if new_state_b:
            logger.warning('Set fan open-drain state: 100%')
            self._state = 100
        else:
            logger.warning('Set fan open-drain state: 0%')
            self._state = 0
