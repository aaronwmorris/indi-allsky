import logging

from .dewHeaterBase import DewHeaterBase
from ..openDrainMixin import OpenDrainPinMixin


logger = logging.getLogger('indi_allsky')


class DewHeaterOpenDrain(OpenDrainPinMixin, DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterOpenDrain, self).__init__(*args, **kwargs)

        self._init_open_drain_pin(
            kwargs['pin_1_name'],
            kwargs['invert_output'],
            'DEW HEATER',
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
            logger.warning('Set dew heater open-drain state: 100%')
            self._state = 100
        else:
            logger.warning('Set dew heater open-drain state: 0%')
            self._state = 0
