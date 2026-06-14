from .. import constants
import logging

from .exposureBase import IndiAllSky_Exposure_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Exposure_Legacy_Auto_Gain(IndiAllSky_Exposure_Base):
    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Exposure_Legacy_Auto_Gain, self).__init__(*args, **kwargs)


        self._gain_step = None  # calculate on first image
        self.auto_gain_step_list = None  # list of fixed gain values
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
    def gain_step(self):
        return self._gain_step


    def adjust_exposure_gain(self, current_exposure, current_gain, next_exposure):
        if isinstance(self.gain_step, type(None)):
            self.post_init()


        try:
            auto_gain_idx = self.auto_gain_step_list.index(current_gain)
        except ValueError:
            # fallback to min if gain does not match
            logger.error('Current gain not found in list, reset to minimum gain')
            auto_gain_idx = 0


        if next_exposure == current_exposure:
            # no change
            #logger.warning('Auto-Gain - no changes')
            next_gain = current_gain
            exposure_delta = 0.0
            gain_delta = 0.0
        elif next_exposure > current_exposure:
            # exposure/gain needs to increase
            if current_gain == self.auto_gain_step_list[-1]:
                # already at max gain, increase exposure
                next_gain = current_gain
                exposure_delta = next_exposure - current_exposure
                gain_delta = 0.0
                logger.info('Auto-Gain increasing exposure to %0.6f (%+0.8f) [max gain]', next_exposure, exposure_delta)
            else:
                if current_exposure < self.auto_gain_exposure_cutoff_high:
                    # maintain gain, increase exposure
                    next_gain = current_gain
                    next_exposure = min(next_exposure, self.auto_gain_exposure_cutoff_high)  # prevent hitting max exposure
                    exposure_delta = next_exposure - current_exposure
                    gain_delta = 0.0
                    logger.info('Auto-Gain increasing exposure to %0.6f (%+0.8f) [maintain gain]', next_exposure, exposure_delta)
                else:
                    # increase gain, maintain exposure
                    next_gain = self.auto_gain_step_list[auto_gain_idx + 1]
                    next_exposure = min(current_exposure, self.auto_gain_exposure_cutoff_high)  # prevent hitting max exposure
                    exposure_delta = 0.0
                    gain_delta = next_gain - current_gain
                    logger.info('Auto-Gain increasing gain to %0.2f (%+0.2f) [maintain exposure]', next_gain, gain_delta)

        else:
            # exposure/gain needs to decrease
            if current_gain == self.auto_gain_step_list[0]:
                # already at minimum gain, decrease exposure
                next_gain = current_gain
                exposure_delta = next_exposure - current_exposure
                gain_delta = 0.0
                logger.info('Auto-Gain decreasing exposure to %0.6f (%+0.8f) [minimum gain]', next_exposure, exposure_delta)
            else:
                if current_exposure > self.auto_gain_exposure_cutoff_low:
                    # maintain gain, decrease exposure
                    next_gain = current_gain
                    next_exposure = max(next_exposure, self.auto_gain_exposure_cutoff_low)
                    exposure_delta = next_exposure - current_exposure
                    gain_delta = 0.0
                    logger.info('Auto-Gain decreasing exposure to %0.6f (%+0.8f) [maintain gain]', next_exposure, exposure_delta)
                else:
                    # decrease gain, maintain exposure
                    next_gain = self.auto_gain_step_list[auto_gain_idx - 1]
                    #next_exposure = max(exposure, self.auto_gain_exposure_cutoff_low)
                    next_exposure = max(current_exposure, self.auto_gain_exposure_cutoff_mid)
                    exposure_delta = 0.0
                    gain_delta = next_gain - current_gain
                    logger.info('Auto-Gain decreasing gain to %0.2f (%+0.2f) [maintain exposure)', next_gain, gain_delta)


        return next_exposure, next_gain, exposure_delta, gain_delta


    def post_init(self):
        # the gain steps cannot be calculated until the gain_av variable is populated
        gain_range = self.gain_av[constants.GAIN_MAX_NIGHT] - self.gain_av[constants.GAIN_MIN_NIGHT]
        auto_gain_levels = self.config.get('CCD_CONFIG', {}).get('AUTO_GAIN_LEVELS', 8)


        self._gain_step = gain_range / (auto_gain_levels - 1)  # need divisions

        self.auto_gain_step_list = [float(round((self.gain_step * x) + self.gain_av[constants.GAIN_MIN_NIGHT], 2)) for x in range(auto_gain_levels)]
        self.auto_gain_step_list[-1] = float(round(self.gain_av[constants.GAIN_MAX_NIGHT], 2))  # replace last value, round is necessary


        self.auto_gain_exposure_cutoff_high = self.exposure_av[constants.EXPOSURE_MAX] - 0.5

        self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] * (self.auto_gain_exposure_cutoff_level_low / 100)
        if self.exposure_av[constants.EXPOSURE_MAX] - self.auto_gain_exposure_cutoff_low > 10.0:
            self.auto_gain_exposure_cutoff_low = self.exposure_av[constants.EXPOSURE_MAX] - 10.0

        self.auto_gain_exposure_cutoff_mid = self.auto_gain_exposure_cutoff_high - ((self.auto_gain_exposure_cutoff_high - self.auto_gain_exposure_cutoff_low) / 2)


        logger.info('Gain Steps: %d @ %0.2f', auto_gain_levels, self.gain_step)
        logger.info('Gain Step list: %s', str(self.auto_gain_step_list))
        logger.info(
            'Auto-Gain Exposure cutoff: Low: %0.2fs - Mid: %0.2fs - High: %0.2fs',
            self.auto_gain_exposure_cutoff_low,
            self.auto_gain_exposure_cutoff_mid,
            self.auto_gain_exposure_cutoff_high,
        )

