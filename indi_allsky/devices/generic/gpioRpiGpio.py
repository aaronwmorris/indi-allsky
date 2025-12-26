import time
import logging

from .genericBase import GenericBase
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class GpioRpiGpio(GenericBase):

    def __init__(self, *args, **kwargs):
        super(GpioRpiGpio, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        self.gpio_pin = int(pin_1_name)

        import RPi.GPIO as GPIO


        try:
            #GPIO.setmode(GPIO.BOARD)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.gpio_pin, GPIO.OUT)
        except GPIO.lgpio.error as e:
            logger.error('GPIO exception: %s', str(e))
            raise DeviceControlException from e


        self._state = bool(GPIO.input(self.gpio_pin))

        time.sleep(0.25)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        new_state_b = bool(new_state)


        import RPi.GPIO as GPIO

        if new_state_b:
            logger.warning('Set gpio state: HIGH')
            GPIO.output(self.gpio_pin, GPIO.HIGH)
            self._state = True
        else:
            logger.warning('Set gpio state: LOW')
            GPIO.output(self.gpio_pin, GPIO.LOW)
            self._state = False


    def deinit(self):
        super(GpioRpiGpio, self).deinit()

        import RPi.GPIO as GPIO

        GPIO.cleanup(self.gpio_pin)  # this will return the pin to the default state
