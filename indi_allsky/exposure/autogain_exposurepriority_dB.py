import math
import logging

from .. import constants
from .exposureBase import IndiAllSky_Exposure_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base(IndiAllSky_Exposure_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base, self).__init__(*args, **kwargs)

        self.auto_gain_exposure_cutoff_low = None
        self.auto_gain_exposure_cutoff_mid = None
        self.auto_gain_exposure_cutoff_high = None


    @property
    def exposure_min(self):
        if self.night_av[constants.NIGHT_NIGHT]:
            return float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])
        else:
            return float(self.exposure_av[constants.EXPOSURE_MIN_DAY])

    @property
    def gain_min(self):
        return float(self.gain_av[constants.GAIN_MIN_NIGHT])

    @property
    def gain_max(self):
        return float(self.gain_av[constants.GAIN_MAX_NIGHT])


    @property
    def gain_min_db(self):
        return self.gain2dB(self.gain_min)

    @property
    def gain_max_db(self):
        return self.gain2dB(self.gain_max)


    def gain2dB(self, gain):
        raise Exception('Not Implemented')

    def dB2gain(self, dB):
        raise Exception('Not Implemented')


    def adjust_exposure_gain(self, current_exposure, current_gain, next_exposure) -> tuple[float, float, float, float]:
        if isinstance(self.auto_gain_exposure_cutoff_low, type(None)):
            self.post_init()


        current_gain_dB = self.gain2dB(current_gain)


        # if you change the exposure  to the next_exposure, you would need to adjust the gain to this value to maintain the same brightness
        maintain_brightness_gain_dB = current_gain_dB + (20 * math.log10(current_exposure / next_exposure))
        maintain_brightness_gain_dB_offset = current_gain_dB - maintain_brightness_gain_dB


        #original_exposure = current_exposure * (10 ** ((current_gain_dB - new_gain_dB) / 20))
        #original_next_exposure = current_exposure * (10 ** (((current_gain_dB + new_gain_dB_offset) - current_gain_dB) / 20))


        if next_exposure == current_exposure:
            # no change
            #logger.warning('Auto-Gain - no changes')
            next_gain_dB = current_gain_dB
            exposure_delta = 0.0
            gain_delta = 0.0
        elif next_exposure > current_exposure:
            # exposure/gain needs to increase
            if current_gain == self.gain_max:
                # already at max gain, increase exposure
                pass
            else:
                if current_exposure < self.auto_gain_exposure_cutoff_high:
                    # maintain gain, increase exposure
                    pass
                else:
                    # increase gain, maintain exposure
                    pass
        else:
            # exposure/gain needs to decrease
            if current_gain == self.gain_min:
                pass
            else:
                if current_exposure > self.auto_gain_exposure_cutoff_low:
                    # maintain gain, decrease exposure
                    pass
                else:
                    # decrease gain, maintain exposure
                    pass


        next_gain = self.dB2gain(next_gain_dB)

        return next_exposure, next_gain, exposure_delta, gain_delta


    def post_init(self):
        self.auto_gain_exposure_cutoff_high = self.exposure_av[constants.EXPOSURE_MAX] - 0.5

        self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] * (self.auto_gain_exposure_cutoff_level_low / 100)
        if self.exposure_av[constants.EXPOSURE_MAX] - self.auto_gain_exposure_cutoff_low > 10.0:
            self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] - 10.0

        self.auto_gain_exposure_cutoff_mid = self.auto_gain_exposure_cutoff_high - ((self.auto_gain_exposure_cutoff_high - self.auto_gain_exposure_cutoff_low) / 2)


        logger.info(
            'Auto-Gain Exposure cutoff: Low: %0.2fs - Mid: %0.2fs - High: %0.2fs',
            self.auto_gain_exposure_cutoff_low,
            self.auto_gain_exposure_cutoff_mid,
            self.auto_gain_exposure_cutoff_high,
        )



class IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_ZWOASI(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_ZWOASI, self).__init__(*args, **kwargs)


    def gain2dB(self, gain):
        return gain / 10.0

    def dB2gain(self, dB):
        return dB * 10.0
