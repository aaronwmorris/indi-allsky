#import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterDigital(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterDigital, self).__init__(*args, **kwargs)

        import board
        import digitalio

        pin1 = getattr(board, self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined'))

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT

        logger.info('Setting initial state of dew heater to OFF')
        self.__duty_cycle = 0
        self.pins[0].value = 0


    @property
    def duty_cycle(self):
        return self.__duty_cycle


    @duty_cycle.setter
    def duty_cycle(self, new_duty_cycle):
        # any positive value is ON
        new_duty_cycle_b = bool(new_duty_cycle)

        if new_duty_cycle_b:
            logger.warning('Set dew heater state: 100%')
            self.pin.value = 1
            self.__duty_cycle = 100
        else:
            logger.warning('Set dew heater state: 0%')
            self.pin.value = 0
            self.__duty_cycle = 0


    def disable(self):
        self.duty_cycle = 0

