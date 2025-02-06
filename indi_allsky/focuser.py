from .devices import focusers
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllSkyFocuserInterface(object):

    def __init__(self, config):
        self.config = config


        focuser_class_str = self.config.get('FOCUSER', {}).get('CLASSNAME', '')

        if not focuser_class_str:
            focuser_class_str = 'focuser_simulator'

        focuser_class = getattr(focusers, focuser_class_str)


        pin1 = self.config.get('FOCUSER', {}).get('GPIO_PIN_1', 'notdefined')
        pin2 = self.config.get('FOCUSER', {}).get('GPIO_PIN_2', 'notdefined')
        pin3 = self.config.get('FOCUSER', {}).get('GPIO_PIN_3', 'notdefined')
        pin4 = self.config.get('FOCUSER', {}).get('GPIO_PIN_4', 'notdefined')

        self.__focuser = focuser_class(self.config, pin_names=[pin1, pin2, pin3, pin4])


    @property
    def focuser(self):
        return self.__focuser


    def move(self, direction, step):
        return self.focuser.move(direction, step)


    def deinit(self):
        self.focuser.deinit()

