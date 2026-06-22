import math
import logging

from .. import constants
from .exposureBase import IndiAllSky_Exposure_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base(IndiAllSky_Exposure_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base, self).__init__(*args, **kwargs)


    @property
    def exposure_min(self):
        if self.night_av[constants.NIGHT_NIGHT]:
            return float(self.exposure_av[constants.EXPOSURE_MIN_NIGHT])
        else:
            return float(self.exposure_av[constants.EXPOSURE_MIN_DAY])

    @property
    def exposure_max(self):
        return float(self.exposure_av[constants.EXPOSURE_MAX])


    @property
    def gain_min(self):
        # prevent python/C float conversion errors
        return math.ceil(float(self.gain_av[constants.GAIN_MIN_NIGHT]) * 100) / 100  # round up the hundredths spot

    @property
    def gain_max(self):
        # prevent python/C float conversion errors
        return math.floor(float(self.gain_av[constants.GAIN_MAX_NIGHT]) * 100) / 100  # round down


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
        #if isinstance(self.auto_gain_exposure_cutoff_low, type(None)):
        #    self.post_init()

        logger.warning('Next calculated exposure: %0.8f', next_exposure)

        # the next exposure may be higher than the maximum exposure
        # this exposure will be used to calulate a gain adjustment instead

        current_gain_dB = self.gain2dB(current_gain)


        if next_exposure == current_exposure:
            # no change
            #logger.warning('Auto-Gain - no changes')
            next_gain_dB = current_gain_dB
            gain_delta = 0.0
            #next_exposure = next_exposure
            exposure_delta = 0.0
        elif next_exposure > current_exposure:
            # exposure/gain needs to increase
            if current_exposure < self.exposure_max:
                # increase exposure
                next_exposure, exposure_delta, next_gain_dB, gain_delta = self.increase_exposure(current_exposure, current_gain, next_exposure)
            else:
                # increase gain, exposure already at max
                next_exposure, exposure_delta, next_gain_dB, gain_delta = self.increase_gain(current_exposure, current_gain, next_exposure)

        else:
            # exposure/gain needs to decrease
            if current_gain > self.gain_min:
                # decrease gain
                next_exposure, exposure_delta, next_gain_dB, gain_delta = self.reduce_gain(current_exposure, current_gain, next_exposure)
            else:
                # decrease exposure, gain already at minimum
                next_exposure, exposure_delta, next_gain_dB, gain_delta = self.reduce_exposure(current_exposure, current_gain, next_exposure, self.exposure_min)

        next_gain = self.dB2gain(next_gain_dB)

        return next_exposure, next_gain, exposure_delta, gain_delta


    def increase_exposure(self, current_exposure, current_gain, next_exposure) -> tuple[float, float, float, float]:
        current_gain_dB = self.gain2dB(current_gain)

        if next_exposure > self.exposure_max:
            # increase exposure, then increase gain

            next_gain_dB = current_gain_dB + (20 * math.log10(next_exposure / self.exposure_max))

            if next_gain_dB > self.gain2dB(self.gain_max):
                next_gain_dB = self.gain2dB(self.gain_max)


            gain_delta = self.dB2gain(next_gain_dB) - current_gain

            next_exposure = self.exposure_max
            exposure_delta = next_exposure - current_exposure

            logger.info('Auto-Gain increasing exposure to %0.6f (%+0.8f), gain to %0.2f (%+0.2f)', next_exposure, exposure_delta, self.dB2gain(next_gain_dB), gain_delta)
        else:
            # increase exposure only
            #next_exposure = next_exposure
            exposure_delta = next_exposure - current_exposure

            next_gain_dB = current_gain_dB
            gain_delta = 0.0

            logger.info('Auto-Gain increasing exposure to %0.6f (%+0.8f) [maintain gain]', next_exposure, exposure_delta)


        return next_exposure, exposure_delta, next_gain_dB, gain_delta


    def reduce_exposure(self, current_exposure, current_gain, next_exposure, exposure_low_cutoff) -> tuple[float, float, float, float]:
        current_gain_dB = self.gain2dB(current_gain)

        if next_exposure >= exposure_low_cutoff:
            # only reduce exposure

            #next_exposure = next_exposure
            exposure_delta = next_exposure - current_exposure
            gain_delta = 0.0
            next_gain_dB = current_gain_dB
            logger.info('Auto-Gain decreasing exposure to %0.6f (%+0.8f) [maintain gain]', next_exposure, exposure_delta)

        else:
            # reduce exposure, then reduce gain

            next_gain_dB = current_gain_dB + (20 * math.log10(next_exposure / exposure_low_cutoff))
            #logger.info('Next Gain dB: %0.4f', next_gain_dB)

            if next_gain_dB < self.gain2dB(self.gain_min):
                next_gain_dB = self.gain2dB(self.gain_min)


            gain_delta = self.dB2gain(next_gain_dB) - current_gain

            next_exposure = exposure_low_cutoff
            exposure_delta = next_exposure - current_exposure

            logger.info('Auto-Gain decreasing exposure to %0.6f (%+0.8f), gain to %0.2f (%+0.2f)', next_exposure, exposure_delta, self.dB2gain(next_gain_dB), gain_delta)

        return next_exposure, exposure_delta, next_gain_dB, gain_delta


    def increase_gain(self, current_exposure, current_gain, next_exposure) -> tuple[float, float, float, float]:
        current_gain_dB = self.gain2dB(current_gain)

        next_gain_dB = current_gain_dB + (20 * math.log10(next_exposure / current_exposure))
        #logger.info('Next Gain dB: %0.4f', next_gain_dB)


        if next_gain_dB > self.gain2dB(self.gain_max):
            # increase gain, then increase exposure
            next_exposure = current_exposure * (10 ** ((next_gain_dB - self.gain2dB(self.gain_max)) / 20))

            if next_exposure > self.exposure_max:
                next_exposure = self.exposure_max

            exposure_delta = next_exposure - current_exposure

            next_gain_dB = self.gain2dB(self.gain_max)
            gain_delta = self.dB2gain(next_gain_dB) - current_gain

            logger.info('Auto-Gain increasing exposure to %0.6f (%+0.8f), gain to %0.2f (%+0.2f)', next_exposure, exposure_delta, self.dB2gain(next_gain_dB), gain_delta)

        else:
            # increase gain only
            next_exposure = current_exposure
            exposure_delta = 0.0
            gain_delta = self.dB2gain(next_gain_dB) - current_gain

            logger.info('Auto-Gain increasing gain to %0.2f (%+0.2f) [maintain exposure]', self.dB2gain(next_gain_dB), gain_delta)


        return next_exposure, exposure_delta, next_gain_dB, gain_delta


    def reduce_gain(self, current_exposure, current_gain, next_exposure) -> tuple[float, float, float, float]:
        current_gain_dB = self.gain2dB(current_gain)


        next_gain_dB = current_gain_dB + (20 * math.log10(next_exposure / current_exposure))
        #logger.info('Next Gain dB: %0.4f', next_gain_dB)


        if self.dB2gain(next_gain_dB) < self.gain_min:
            # reduce gain, then reduce exposure
            next_exposure = current_exposure * (10 ** ((self.gain2dB(self.gain_min) + next_gain_dB) / 20))  # next_gain_dB is negative

            if next_exposure < self.exposure_min:
                next_exposure = self.exposure_min

            exposure_delta = next_exposure - current_exposure

            next_gain_dB = self.gain2dB(self.gain_min)
            gain_delta = self.dB2gain(next_gain_dB) - current_gain

            logger.info('Auto-Gain decreasing exposure to %0.6f (%+0.8f), gain to %0.2f (%+0.2f)', next_exposure, exposure_delta, self.dB2gain(next_gain_dB), gain_delta)

        else:
            # reduce only gain
            gain_delta = self.dB2gain(next_gain_dB) - current_gain
            next_exposure = current_exposure
            exposure_delta = 0.0
            logger.info('Auto-Gain decreasing gain to %0.2f dB (%+0.2f) [maintain exposure]', self.dB2gain(next_gain_dB), gain_delta)

        return next_exposure, exposure_delta, next_gain_dB, gain_delta


    def post_init(self):
        pass


class IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_1_10(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_1_10, self).__init__(*args, **kwargs)


    ### 1 gain = 0.1 dB (/10)
    ### ZWO, PlayerOne


    def gain2dB(self, gain) -> float:
        return gain / 10.0

    def dB2gain(self, dB) -> float:
        return dB * 10.0


class IndiAllSky_Exposure_AutoGain_ExposurePriority_dB(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB, self).__init__(*args, **kwargs)

    ### 1 gain = 1 dB (1:1)
    ### QHY


    def gain2dB(self, gain) -> float:
        return gain

    def dB2gain(self, dB) -> float:
        return dB


class IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO, self).__init__(*args, **kwargs)

    ### 100 gain = ISO 100 (1:1)
    ### ToupTek, Altair, QHY, etc


    def gain2dB(self, gain) -> float:
        return 20 * math.log10(gain / 100)

    def dB2gain(self, dB) -> float:
        return 100 * (10 ** (dB / 20))


class IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO_1_100(IndiAllSky_Exposure_AutoGain_ExposurePriority_dB_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_AutoGain_ExposurePriority_ISO_1_100, self).__init__(*args, **kwargs)


    ### 1 gain = ISO 100 (*100)
    ### libcamera

    # Treat the gain like ISO
    # gain 1 is the baseline of 0 dB


    def gain2dB(self, gain) -> float:
        return 20 * math.log10(gain)

    def dB2gain(self, dB) -> float:
        return 10 ** (dB / 20)
