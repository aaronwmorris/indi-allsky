#from .. import constants


class IndiAllSky_Exposure_Base(object):

    auto_gain_exposure_cutoff_level_low = 80  # percent of max exposure


    def __init__(self, *args, **kwargs):
        self.config = args[0]
        self.exposure_av = args[1]
        self.gain_av = args[2]
        self.night_av = args[3]


        #self._exposure_min = None
        #self._exposure_max = None
        #self._gain_min = None
        #self._gain_max = None


    #@property
    #def exposure_min(self):
    #    if self.night_av[constants.NIGHT_NIGHT]:
    #        return float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])
    #    else:
    #        return float(self.exposure_av[constants.EXPOSURE_MIN_DAY])

    #@property
    #def exposure_max(self):
    #    return self._exposure_max


    #@property
    #def gain_min(self):
    #    return float(self.gain_av[constants.GAIN_MIN_NIGHT])

    #@property
    #def gain_max(self):
    #    return float(self.gain_av[constants.GAIN_MAX_NIGHT])


    def recalculate(self, *args):
        raise Exception('Not implemented')
