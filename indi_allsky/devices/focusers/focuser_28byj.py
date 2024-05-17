import board
import digitalio
import time
import logging

from .focuserBase import FocuserBase

logger = logging.getLogger('indi_allsky')


class focuser_28byj_64(FocuserBase):
    # 1/64 ratio

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


    STEP_DEGREES = {
        6   : 8,
        12  : 17,
        24  : 34,
        45  : 64,
        90  : 128,
        180 : 256,
    }


    def __init__(self, *args, **kwargs):
        super(focuser_28byj_16, self).__init__(*args, **kwargs)

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


    def move(self, direction, degrees):
        steps = self.STEP_DEGREES[degrees]

        self.set_step(0, 0, 0, 0)  # reset
        self.step(direction, steps)
        self.set_step(0, 0, 0, 0)  # reset

        if direction == 'ccw':
            #steps *= -1  # negative for CCW
            degrees *= -1

        return degrees


    def set_step(self, w1, w2, w3, w4):
        self.pins[0].value = w1
        self.pins[1].value = w2
        self.pins[2].value = w3
        self.pins[3].value = w4


    def step(self, direction, steps):
        if direction == 'cw':  # CW
            seq = self.SEQ[::-1]
        else:  # CCW
            seq = self.SEQ


        for i in range(steps):
            for j in seq:
                self.set_step(*j)
                time.sleep(0.005)


class focuser_28byj_16(focuser_28byj_64):
    # 1/16 ratio

    ### untested
    STEP_DEGREES = {
        6   : 2,
        12  : 4,
        24  : 9,
        45  : 16,
        90  : 32,
        180 : 64,
    }


