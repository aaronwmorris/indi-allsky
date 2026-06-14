#from .. import constants


class IndiAllSky_Exposure_Base(object):

    auto_gain_exposure_cutoff_level_low = 80  # percent of max exposure


    def __init__(self, *args, **kwargs):
        self.config = args[0]
        self.exposure_av = args[1]
        self.gain_av = args[2]
        self.night_av = args[3]


    def recalculate_exposure(self, *args):
        raise Exception('Not implemented')

