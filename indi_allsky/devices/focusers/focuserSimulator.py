# This is a fake device that acts like a focuser but does not actually do anything
import logging

from .focuserBase import FocuserBase


logger = logging.getLogger('indi_allsky')


class FocuserSimulator(FocuserBase):

    def __init__(self, *args, **kwargs):
        super(FocuserSimulator, self).__init__(*args, **kwargs)


    def move(self, direction, degrees):
        steps = degrees

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        return steps
