# This is a fake device that acts like a dew heater but does not actually do anything
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterSimulator(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterSimulator, self).__init__(*args, **kwargs)

        logger.info('Setting initial state of dew heater to OFF (fake)')
        self.__duty_cycle = 0


    @property
    def duty_cycle(self):
        return self.__duty_cycle


    @duty_cycle.setter
    def duty_cycle(self, new_duty_cycle):
        logger.warning('Set dew heater state: %d%% (fake)', int(new_duty_cycle))
        pass


    def disable(self):
        self.duty_cycle = 0

