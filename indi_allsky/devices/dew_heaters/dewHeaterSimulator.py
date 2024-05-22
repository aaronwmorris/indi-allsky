# This is a fake device that acts like a dew heater but does not actually do anything
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterSimulator(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterSimulator, self).__init__(*args, **kwargs)

        self._duty_cycle = None


    @property
    def duty_cycle(self):
        return self._duty_cycle


    @duty_cycle.setter
    def duty_cycle(self, new_duty_cycle):
        #logger.warning('Set dew heater state: %d%% (fake)', int(new_duty_cycle))
        self._duty_cycle = 0  # 0 is intentional


    def disable(self):
        self.duty_cycle = 0

