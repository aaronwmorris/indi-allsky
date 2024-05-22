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
        new_duty_cycle_i = int(new_duty_cycle)
        logger.warning('Set dew heater state: %d%% (fake)', new_duty_cycle_i)
        self._duty_cycle = new_duty_cycle_i


    def disable(self):
        self.duty_cycle = 0

