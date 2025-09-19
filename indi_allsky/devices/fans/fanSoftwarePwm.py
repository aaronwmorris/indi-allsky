import time
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanSoftwarePwmRpiGpio(FanBase):

    PWM_FREQUENCY = 100


    def __init__(self, *args, **kwargs):
        super(FanSoftwarePwmRpiGpio, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']

        pwm_pin = int(pin_1_name)


        import RPi.GPIO as GPIO

        logger.info('Initializing Software PWM FAN device (%d Hz)', self.PWM_FREQUENCY)

        if self.invert_output:
            logger.warning('Fan logic reversed')

        #GPIO.setmode(GPIO.BOARD)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pwm_pin, GPIO.OUT)

        self.pwm = GPIO.PWM(pwm_pin, self.PWM_FREQUENCY)
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


        if self.invert_output:
            new_duty_cycle = int(100 * (100 - new_state_i) / 100)
        else:
            new_duty_cycle = int(100 * new_state_i / 100)


        logger.warning('Set fan state: %d%%', new_state_i)
        self.pwm.ChangeDutyCycle(new_duty_cycle)

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(FanSoftwarePwmRpiGpio, self).deinit()


class FanSoftwarePwmGpiozero(FanBase):

    PWM_FREQUENCY = 100


    def __init__(self, *args, **kwargs):
        super(FanSoftwarePwmGpiozero, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']

        pwm_pin = int(pin_1_name)


        from gpiozero import PWMOutputDevice

        logger.info('Initializing Software PWM FAN device (%d Hz)', self.PWM_FREQUENCY)

        self.pwm = PWMOutputDevice(pwm_pin, initial_value=0, frequency=self.PWM_FREQUENCY)

        if self.invert_output:
            logger.warning('Fan logic reversed')

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


        if self.invert_output:
            new_duty_cycle = 1 - (new_state_i / 100)
        else:
            new_duty_cycle = new_state_i / 100


        logger.warning('Set fan state: %d%%', new_state_i)
        self.pwm.value = new_duty_cycle

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(FanSoftwarePwmGpiozero, self).deinit()

