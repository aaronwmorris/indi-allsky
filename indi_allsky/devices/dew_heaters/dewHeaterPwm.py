import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterPwm(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterPwm, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']

        import board
        import pwmio

        logger.info('Initializing PWM DEW HEATER device')

        if self.invert_output:
            logger.warning('Dew heater logic reversed')

        pwm_pin = getattr(board, pin_1_name)

        self.pwm = pwmio.PWMOut(pwm_pin)

        self._state = -1

        time.sleep(1.0)


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


        if self.invert_output:
            new_duty_cycle = int(((2 ** 16) - 1) * (100 - new_state_i) / 100)
        else:
            new_duty_cycle = int(((2 ** 16) - 1) * new_state_i / 100)


        logger.warning('Set dew heater state: %d%%', new_state_i)
        self.pwm.duty_cycle = new_duty_cycle

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(DewHeaterPwm, self).deinit()
        self.pwm.deinit()

