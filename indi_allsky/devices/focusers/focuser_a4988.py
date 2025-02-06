import board
import digitalio
import time
import logging

from .focuserBase import FocuserBase

logger = logging.getLogger('indi_allsky')


class focuser_a4988(FocuserBase):

    def __init__(self, *args, **kwargs):
        super(focuser_a4988, self).__init__(*args, **kwargs)

        self._sleep = False

        pin_names = kwargs['pin_names']

        pin1 = getattr(board, pin_names[0])
        pin2 = getattr(board, pin_names[1])
        pin3 = getattr(board, pin_names[2])
        pin4 = getattr(board, pin_names[3])

        self.pins = {
            'step'    : digitalio.DigitalInOut(pin1),
            'dir'     : digitalio.DigitalInOut(pin2),
            'ms1'     : digitalio.DigitalInOut(pin3),
            'sleep'   : digitalio.DigitalInOut(pin4),
        }

        for label, pin in self.pins.items():
            # set all pins to output
            pin.direction = digitalio.Direction.OUTPUT


    @property
    def sleep(self):
        return self._sleep


    @sleep.setter
    def sleep(self, new_sleep):
        new_sleep_b = bool(new_sleep)


        if not new_sleep_b:
            self.pins['sleep'].value = 0
            time.sleep(0.001)  # wait for 1ms
        else:
            self.pins['sleep'].value = 1


        self._sleep = new_sleep_b


    def move(self, direction, degrees):
        steps = round(degrees / (360 / self.STEPS))

        self.step(direction, steps)

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        return steps


    def step(self, direction, steps):
        if direction == 'cw':  # CW
            self.pins['dir'].value = 1
        else:  # CCW
            self.pins['dir'].value = 0


        # disable sleep
        self.sleep = False


        for i in range(steps):
            self.pins['step'].value = 1
            time.sleep(0.005)
            self.pins['step'].value = 0
            time.sleep(0.005)


        # re-enable sleep
        self.sleep = True


class focuser_a4988_nema17_full(focuser_a4988):
    # full step 1.8 degrees per step
    STEPS = 200


    def __init__(self, *args, **kwargs):
        super(focuser_a4988_nema17_full, self).__init__(*args, **kwargs)

        self.pins['ms1'].value = 0


class focuser_a4988_nema17_half(focuser_a4988):
    # half step 0.9 degrees per step
    STEPS = 400


    def __init__(self, *args, **kwargs):
        super(focuser_a4988_nema17_half, self).__init__(*args, **kwargs)

        self.pins['ms1'].value = 1


#class focuser_a4988_nema17_quarter(focuser_a4988):
#    # quarter step 0.45 degrees per step
#    STEPS = 800
#
#
#    def __init__(self, *args, **kwargs):
#        super(focuser_a4988_nema17_quarter, self).__init__(*args, **kwargs)
#
#        self.pins['ms1'].value = 0
#        self.pins['ms2'].value = 1
#
#
#class focuser_a4988_nema17_eighth(focuser_a4988):
#    # eighth step 0.225 degrees per step
#    STEPS = 1600
#
#
#    def __init__(self, *args, **kwargs):
#        super(focuser_a4988_nema17_eighth, self).__init__(*args, **kwargs)
#
#        self.pins['ms1'].value = 1
#        self.pins['ms2'].value = 1

