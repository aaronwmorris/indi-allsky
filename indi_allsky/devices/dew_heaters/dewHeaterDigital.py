import board
import digitalio
#import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class dewHeaterDigitalHigh(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(dewHeaterDigitalHigh, super).__init__(*args, **kwargs)

        pin1 = getattr(board, self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined'))

        self.pin = digitalio.DigitalInOut(pin1)
        self.pin.direction = digitalio.Direction.OUTPUT

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
            self.pin.value = 1
            self.__duty_cycle = 100
        else:
            self.pin.value = 0
            self.__duty_cycle = 0


    def disable(self):
        self.duty_cycle = 0

