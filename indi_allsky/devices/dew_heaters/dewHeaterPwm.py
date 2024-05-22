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

        self._state = None


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # duty cycle must be a percentage between 0 and 100
        new_state_i = int(new_state)

        if new_state_i < 0:
            logger.error('Duty cycle must be 0 or greater')
            return

        if new_state_i > 100:
            logger.error('Duty cycle must be 100 or less')
            return


        logger.warning('Set dew heater state: %d%%', new_state_i)

        d = ((2 ** 16) - 1) * new_state_i / 100
        self.pwm.duty_cycle = d

        self._state = new_state_i


    def disable(self):
        self.state = 0
