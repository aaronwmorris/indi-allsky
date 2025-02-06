# This is a fake device that acts like a focuser but does not actually do anything
import logging

from .focuserBase import FocuserBase


logger = logging.getLogger('indi_allsky')


class FocuserSimulator(FocuserBase):

    def __init__(self, *args, **kwargs):
        super(FocuserSimulator, self).__init__(*args, **kwargs)

        self._sleep = False


    @property
    def sleep(self):
        return self._sleep


    @sleep.setter
    def sleep(self, new_sleep):
        pass


    def move(self, *args):
        pass
