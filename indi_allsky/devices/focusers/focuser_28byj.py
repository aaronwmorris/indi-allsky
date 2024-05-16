import board
import digitalio
import time
import logging

from .focuserBase import FocuserBase

logger = logging.getLogger('indi_allsky')


class focuser_28byj(FocuserBase):

    SEQ = (
        (1, 0, 0, 0),
        (1, 1, 0, 0),
        (0, 1, 0, 0),
        (0, 1, 1, 0),
        (0, 0, 1, 0),
        (0, 0, 1, 1),
        (0, 0, 0, 1),
        (1, 0, 0, 1),
    )


    STEP_LENGTH = {
        'short'    : 1,
        'medium'   : 5,
        'long'     : 10,
        'verylong' : 100,
    }


    def __init__(self, *args, **kwargs):
        super(focuser_28byj, self).__init__(*args, **kwargs)

        pin1 = getattr(board, self.config.get('FOCUSER', {}).get('GPIO_PIN_1', 'notdefined'))
        pin2 = getattr(board, self.config.get('FOCUSER', {}).get('GPIO_PIN_2', 'notdefined'))
        pin3 = getattr(board, self.config.get('FOCUSER', {}).get('GPIO_PIN_3', 'notdefined'))
        pin4 = getattr(board, self.config.get('FOCUSER', {}).get('GPIO_PIN_4', 'notdefined'))

        self.pins = [
            digitalio.DigitalInOut(pin1),
            digitalio.DigitalInOut(pin2),
            digitalio.DigitalInOut(pin3),
            digitalio.DigitalInOut(pin4),
        ]

        for pin in self.pins:
            # set all pins to output
            pin.direction = digitalio.Direction.OUTPUT


    def move(self, direction, step_length):
        self.set_step(0, 0, 0, 0)  # reset
        self.step(direction, self.STEP_LENGTH[step_length])
        self.set_step(0, 0, 0, 0)  # reset


    def set_step(self, w1, w2, w3, w4):
        self.pins[0].value = w1
        self.pins[1].value = w2
        self.pins[2].value = w3
        self.pins[3].value = w4


    def step(self, direction, steps):
        if direction:  # CW
            seq = self.SEQ
        else:  # CCW
            seq = self.SEQ[::-1]


        for i in range(steps):
            for j in seq:
                self.set_step(*j)
                time.sleep(0.005)

