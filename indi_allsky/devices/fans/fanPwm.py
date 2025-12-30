import time
import logging

from .fanBase import FanBase

from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class FanPwm(FanBase):

    def __init__(self, *args, **kwargs):
        super(FanPwm, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']
        pwm_frequency = kwargs['pwm_frequency']


        import board
        import pwmio

        logger.info('Initializing PWM FAN device: %s (%d Hz)', str(pin_1_name), pwm_frequency)

        if self.invert_output:
            logger.warning('Fan logic reversed')

        pwm_pin = getattr(board, pin_1_name)


        try:
            self.pwm = pwmio.PWMOut(pwm_pin, frequency=pwm_frequency)
        except Exception as e:  # catch all exceptions, not raspberry pi specific
            logger.error('GPIO exception: %s', str(e))
            raise DeviceControlException from e


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


        logger.warning('Set fan state: %d%%', new_state_i)
        self.pwm.duty_cycle = new_duty_cycle

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(FanPwm, self).deinit()
        self.pwm.deinit()

