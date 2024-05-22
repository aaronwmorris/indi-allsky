#import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterPwm(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterPwm, self).__init__(*args, **kwargs)

        import board
        import pwmio

        pwm_pin = getattr(board, self.config.get('DEW_HEATER', {}).get('PIN_1', 'notdefined'))

        self.pwm = pwmio.PWMOut(pwm_pin)


        logger.info('Setting initial state of dew heater to OFF')
        self.__duty_cycle = 0
        self.pwm.duty_cycle = 0


    @property
    def duty_cycle(self):
        return self.__duty_cycle


    @duty_cycle.setter
    def duty_cycle(self, new_duty_cycle):
        # duty cycle must be a percentage between 0 and 100
        new_duty_cycle_i = int(new_duty_cycle)

        if new_duty_cycle_i < 0:
            logger.error('Duty cycle must be 0 or greater')
            return

        if new_duty_cycle_i > 100:
            logger.error('Duty cycle must be 100 or less')
            return


        logger.warning('Set dew heater state: %d%%', new_duty_cycle_i)

        d = (2 ** 16) * new_duty_cycle_i / 100
        self.pwm.duty_cycle = d

        self.__duty_cycle = new_duty_cycle_i


    def disable(self):
        self.duty_cycle = 0
