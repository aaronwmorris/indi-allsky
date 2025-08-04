import time
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanSoftwarePwmRpiGpio(FanBase):

    def __init__(self, *args, **kwargs):
        super(FanSoftwarePwmRpiGpio, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']

        pwm_pin = int(pin_1_name)


        import RPi.GPIO as GPIO

        logger.info('Initializing Software PWM FAN device')

        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(pwm_pin, GPIO.OUT)

        self.pwm = GPIO.PWM(pwm_pin, 50)
        self.pwm.start(0)

        self._state = 0

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


        if not self.invert_output:
            new_duty_cycle = int(100 * new_state_i / 100)
        else:
            new_duty_cycle = int(100 * (100 - new_state_i) / 100)


        logger.warning('Set fan state: %d%%', new_state_i)
        self.pwm.ChangeDutyCycle(new_duty_cycle)

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(FanSoftwarePwmRpiGpio, self).deinit()

