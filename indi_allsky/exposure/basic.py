from .. import constants
import logging

from .exposureBase import IndiAllSky_Exposure_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Exposure_Basic(IndiAllSky_Exposure_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_Basic, self).__init__(*args, **kwargs)


    @property
    def exposure_min(self):
        if self.night_av[constants.NIGHT_NIGHT]:
            # night
            return float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])
        else:
            # day
            return float(self.exposure_av[constants.EXPOSURE_MIN_DAY])

    @property
    def exposure_max(self):
        return float(self.exposure_av[constants.EXPOSURE_MAX])


    @property
    def gain_min(self):
        if self.night_av[constants.NIGHT_NIGHT]:
            if self.night_av[constants.NIGHT_MOONMODE]:
                # moon mode
                return float(self.gain_av[constants.GAIN_MIN_MOONMODE])
            else:
                # night
                return float(self.gain_av[constants.GAIN_MIN_NIGHT])

        else:
            # day
            return float(self.gain_av[constants.GAIN_MIN_DAY])

    @property
    def gain_max(self):
        if self.night_av[constants.NIGHT_NIGHT]:
            if self.night_av[constants.NIGHT_MOONMODE]:
                # moon mode
                return float(self.gain_av[constants.GAIN_MAX_MOONMODE])
            else:
                # night
                return float(self.gain_av[constants.GAIN_MAX_NIGHT])

        else:
            return float(self.gain_av[constants.GAIN_MAX_DAY])


    def calculate_exposure(self, *args):
        return super(IndiAllSky_Exposure_Basic, self).calculate_exposure(*args)


    def recalculate_exposure(self, *args):
        return super(IndiAllSky_Exposure_Basic, self).recalculate_exposure(*args)


    def adjust_exposure_gain(self, current_exposure, current_gain, next_exposure) -> tuple[float, float, float, float]:
        # just set the gain to the max for the current mode


        # Do not exceed the exposure limits
        if next_exposure < self.exposure_min:
            next_exposure = float(self.exposure_min)
        elif next_exposure > self.exposure_av[constants.EXPOSURE_MAX]:
            next_exposure = float(self.exposure_av[constants.EXPOSURE_MAX])


        next_gain = self.gain_max
        exposure_delta = next_exposure - current_exposure
        gain_delta = 0.0

        return next_exposure, next_gain, exposure_delta, gain_delta
