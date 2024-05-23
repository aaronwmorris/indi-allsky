# This is a fake device that acts like a dew heater but does not actually do anything
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterSimulator(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterSimulator, self).__init__(*args, **kwargs)

        self._state = None


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        #logger.warning('Set dew heater state: %d%% (fake)', int(new_state))
        self._state = 0  # 0 is intentional


    def disable(self):
        self.state = 0

