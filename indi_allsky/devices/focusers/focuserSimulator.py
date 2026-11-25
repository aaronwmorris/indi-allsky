# This is a fake device that acts like a focuser but does not actually do anything
import time
import logging

from .focuserBase import FocuserBase


logger = logging.getLogger('indi_allsky')


# The last simulator constructed, so a simulated camera can read lens_position
SIMULATED_LENS = None


class FocuserSimulator(FocuserBase):

    STEPS_PER_TURN = 512
    STEPS_PER_SECOND = 200
    CAN_STOP = True


    def __init__(self, *args, **kwargs):
        global SIMULATED_LENS

        super(FocuserSimulator, self).__init__(*args, **kwargs)

        self.position = 0  # true shaft position, steps, positive is outward
        self.backlash_steps = 26  # gear backlash

        # The lens is the shaft position plus the play (0 to backlash_steps).  After a reversal the
        # shaft moves backlash_steps through the play before the lens follows it.
        self._play = 0

        SIMULATED_LENS = self


    @property
    def lens_position(self):
        return float(self.position + self._play)


    def move(self, direction, degrees):
        steps = degrees

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        # simulate waiting for movement to complete
        time.sleep(1.0)

        return steps


    def move_steps(self, steps, should_stop=None):
        steps = int(steps)
        sign = 1 if steps > 0 else -1

        moved = 0
        for _ in range(abs(steps)):
            time.sleep(1 / self.STEPS_PER_SECOND)

            self.position += sign

            if sign > 0:
                if self._play > 0:
                    self._play -= 1
            else:
                if self._play < self.backlash_steps:
                    self._play += 1

            moved += sign

            if should_stop is not None and should_stop():
                break

        return moved
