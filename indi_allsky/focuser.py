from .devices import focusers
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllSkyFocuser(object):

    def __init__(self, config):
        self.config = config

        focuser_class = getattr(focusers, self.config.get('FOCUSER', {}).get('CLASSNAME', 'NotConfigured'))
        self.__focuser = focuser_class(self.config)


    @property
    def focuser(self):
        return self.__focuser


    def move(self, direction, step):
        return self.focuser.move(direction, step)

