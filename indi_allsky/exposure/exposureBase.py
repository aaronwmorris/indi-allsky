import copy
import functools
import logging

from .. import constants


logger = logging.getLogger('indi_allsky')


class IndiAllSky_Exposure_Base(object):

    auto_gain_exposure_cutoff_level_low = 80  # percent of max exposure


    def __init__(self, *args, **kwargs):
        self.config = args[0]
        self.exposure_av = args[1]
        self.gain_av = args[2]
        self.binning_av = args[3]
        self.night_av = args[4]

        self._target_adu_found = False
        self._current_adu_target = 0
        self.hist_adu = []


    @property
    def target_adu_found(self):
        return self._target_adu_found

    @target_adu_found.setter
    def target_adu_found(self, new_target_adu_found):
        self._target_adu_found = bool(new_target_adu_found)


    @property
    def current_adu_target(self):
        return self._current_adu_target


    def calculate_exposure(self, adu, exposure, gain):
        if adu <= 0.0:
            # ensure we do not divide by zero
            logger.warning('Zero average, setting a default of 0.1')
            adu = 0.1


        if self.night_av[constants.NIGHT_NIGHT]:
            target_adu = self.config['TARGET_ADU']
        else:
            target_adu = self.config['TARGET_ADU_DAY']


        # Brightness when the sun is in view (very short exposures) can change drastically when clouds pass through the view
        # Setting a deviation that is too short can cause exposure flapping
        if exposure < 0.001000:
            # DAY
            adu_dev = float(self.config.get('TARGET_ADU_DEV_DAY', 20))

            target_adu_min = target_adu - adu_dev
            target_adu_max = target_adu + adu_dev
            current_adu_target_min = self.current_adu_target - adu_dev
            current_adu_target_max = self.current_adu_target + adu_dev

            exp_scale_factor = 0.50  # scale exposure calculation
            history_max_vals = 6     # number of entries to use to calculate average
        else:
            # NIGHT
            adu_dev = float(self.config.get('TARGET_ADU_DEV', 10))

            target_adu_min = target_adu - adu_dev
            target_adu_max = target_adu + adu_dev
            current_adu_target_min = self.current_adu_target - adu_dev
            current_adu_target_max = self.current_adu_target + adu_dev

            exp_scale_factor = 1.0  # scale exposure calculation
            history_max_vals = 6    # number of entries to use to calculate average



        if not self.target_adu_found:
            self.recalculate_exposure(exposure, gain, adu, target_adu, target_adu_min, target_adu_max, exp_scale_factor)
            return adu, 0.0


        self.hist_adu.append(adu)
        self.hist_adu = self.hist_adu[(history_max_vals * -1):]  # remove oldest values, up to history_max_vals

        adu_average = functools.reduce(lambda a, b: a + b, self.hist_adu) / len(self.hist_adu)

        #logger.info('ADU average: %0.2f', adu_average)
        #logger.info('Current target ADU: %0.2f (%0.2f/%0.2f)', self.current_adu_target, current_adu_target_min, current_adu_target_max)
        #logger.info('Current ADU history: (%d) [%s]', len(self.hist_adu), ', '.join(['{0:0.2f}'.format(x) for x in self.hist_adu]))


        ### Need at least x values to continue
        if len(self.hist_adu) < history_max_vals:
            return adu, 0.0


        ### only change exposure when 70% of the values exceed the max or minimum
        if adu_average > current_adu_target_max:
            logger.warning('ADU increasing beyond limits, recalculating next exposure')
            self.target_adu_found = False
        elif adu_average < current_adu_target_min:
            logger.warning('ADU decreasing beyond limits, recalculating next exposure')
            self.target_adu_found = False

        return adu, adu_average



    def recalculate_exposure(self, current_exposure, current_gain, adu, target_adu, target_adu_min, target_adu_max, exp_scale_factor):
        # There might be a race condition here if there is a day/night change but self.target_adu_found == True

        # Until we reach a good starting point, do not calculate a moving average
        if adu <= target_adu_max and adu >= target_adu_min:
            logger.warning('Found target value for exposure')
            self._current_adu_target = copy.copy(adu)
            self.target_adu_found = True
            self.hist_adu = []
            return


        # Scale the exposure up and down based on targets
        if adu > target_adu_max:
            next_exposure = current_exposure - ((current_exposure - (current_exposure * (target_adu / adu))) * exp_scale_factor)
        elif adu < target_adu_min:
            next_exposure = current_exposure - ((current_exposure - (current_exposure * (target_adu / adu))) * exp_scale_factor)
        else:
            next_exposure = current_exposure


        next_exposure, next_gain, exposure_delta, gain_delta = self.adjust_exposure_gain(current_exposure, current_gain, next_exposure)


        # Do not exceed the gain limits
        if next_gain > self.gain_max:
            next_gain = self.gain_max
        elif next_gain < self.gain_min:
            next_gain = self.gain_min


        # Binning
        if self.night_av[constants.NIGHT_NIGHT]:
            if self.night_av[constants.NIGHT_MOONMODE]:
                next_binning = self.binning_av[constants.BINNING_MOONMODE]
            else:
                next_binning = self.binning_av[constants.BINNING_NIGHT]
        else:
            next_binning = self.binning_av[constants.BINNING_DAY]


        ### Check for exposure flapping
        # Flapping is defined when the exposure increases then immediately decreases (or the opposite)
        # and cannot find a stable value.  The result is the image brightness will flash
        #if self.exposure_av[constants.EXPOSURE_DELTA] > 0 and exposure_delta < 0:
        #    # exposure is decreasing
        #    exposure_offset = exposure_delta / 2
        #    next_exposure -= exposure_offset  # offset will be negative
        #    exposure_delta -= exposure_offset

        #    logger.warning('DETECTED EXPOSURE FLAPPING - Attempting to mitigate by adjusting exposure by %+0.8fs', exposure_offset * -1)
        #elif self.exposure_av[constants.EXPOSURE_DELTA] < 0 and exposure_delta > 0:
        #    # exposure is increasing
        #    exposure_offset = exposure_delta / 2
        #    next_exposure -= exposure_offset
        #    exposure_delta -= exposure_offset

        #    logger.warning('DETECTED EXPOSURE FLAPPING - Attempting to mitigate by adjusting exposure by %+0.8fs', exposure_offset * -1)


        logger.warning('New calculated exposure: %0.6fs (%+0.8f) @ gain %0.2f (%+0.2f) bin %d', next_exposure, exposure_delta, next_gain, gain_delta, next_binning)
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_NEXT] = float(next_exposure)
            self.exposure_av[constants.EXPOSURE_DELTA] = float(exposure_delta)

        with self.gain_av.get_lock():
            self.gain_av[constants.GAIN_NEXT] = float(next_gain)
            self.gain_av[constants.GAIN_DELTA] = float(gain_delta)

        with self.binning_av.get_lock():
            self.binning_av[constants.BINNING_NEXT] = int(next_binning)



    def adjust_exposure_gain(self, *args):
        raise Exception('Not implemented')

