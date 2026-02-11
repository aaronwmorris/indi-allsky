import logging

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Stretch_Base(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]

