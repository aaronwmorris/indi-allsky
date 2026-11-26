import time
import logging

from .focuserBase import FocuserBase

from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class focuser_28byj(FocuserBase):
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


    # override in child class
    STEP_DEGREES = {}
    STEPS_PER_TURN = 512

    # one step is one pass through SEQ, 8 x 5 ms
    STEPS_PER_SECOND = 25
    CAN_STOP = True


    def __init__(self, *args, **kwargs):
        super(focuser_28byj, self).__init__(*args, **kwargs)

        import board
        import digitalio


        pin_names = kwargs['pin_names']

        pin1 = getattr(board, pin_names[0])
        pin2 = getattr(board, pin_names[1])
        pin3 = getattr(board, pin_names[2])
        pin4 = getattr(board, pin_names[3])


        try:
            self.pins = [
                digitalio.DigitalInOut(pin1),
                digitalio.DigitalInOut(pin2),
                digitalio.DigitalInOut(pin3),
                digitalio.DigitalInOut(pin4),
            ]

            for pin in self.pins:
                # set all pins to output
                pin.direction = digitalio.Direction.OUTPUT
        except Exception as e:  # catch all exceptions, not raspberry pi specific
            logger.error('GPIO exception: %s', str(e))
            raise DeviceControlException from e


    def move(self, direction, degrees):
        steps = self.STEP_DEGREES[degrees]

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        return self.move_steps(steps)


    def move_steps(self, steps, should_stop=None):
        self.set_step(0, 0, 0, 0)  # reset

        try:
            moved = self.step(steps, should_stop)
        finally:
            self.set_step(0, 0, 0, 0)  # reset

        return moved


    def set_step(self, w1, w2, w3, w4):
        self.pins[0].value = w1
        self.pins[1].value = w2
        self.pins[2].value = w3
        self.pins[3].value = w4


    def step(self, steps, should_stop=None):
        if steps > 0:  # CW
            seq = self.SEQ[::-1]
            sign = 1
        else:  # CCW
            seq = self.SEQ
            sign = -1


        moved = 0
        for i in range(abs(steps)):
            for j in seq:
                self.set_step(*j)
                time.sleep(0.005)

            moved += sign

            if should_stop is not None and should_stop():
                break

        return moved


    def deinit(self):
        super(focuser_28byj, self).deinit()

        for pin in self.pins:
            pin.deinit()


class focuser_28byj_64(focuser_28byj):
    # 1/64 ratio
    STEPS_PER_TURN = 512

    STEP_DEGREES = {
        6   : 8,
        12  : 17,
        24  : 34,
        45  : 64,
        90  : 128,
        180 : 256,
    }



class focuser_28byj_16(focuser_28byj):
    # 1/16 ratio

    STEPS_PER_TURN = 128

    ### untested
    STEP_DEGREES = {
        6   : 2,
        12  : 4,
        24  : 9,
        45  : 16,
        90  : 32,
        180 : 64,
    }


