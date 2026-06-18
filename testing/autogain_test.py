#!/usr/bin/env python3


import sys
from pathlib import Path
import logging

from multiprocessing import Array


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.config import IndiAllSkyConfig
#from indi_allsky import constants
from indi_allsky import exposure as exposure_module

from indi_allsky.flask import create_app
from sqlalchemy.orm.exc import NoResultFound


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s] %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class AutoGain_Test(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self.exposure_av = Array('f', [
            -1.0,  # current exposure
            -1.0,  # next exposure
            1.0,   # exposure delta
            0.0,   # night minimum
            0.0,   # day minimum
            15.0,  # maximum
            -1.0,  # sqm
        ])


        self.gain_av = Array('f', [
            -1.0,   # current gain
            -1.0,   # next gain
            -1.0,   # gain delta
            0.0,    # day minimum
            300.0,  # day maximum
            0.0,    # night minimum
            300.0,  # night maximum
            0.0,    # moon mode minimum
            200.0,  # moon mode maximum
            -1.0,   # sqm
        ])


        self.binning_av = Array('i', [
            1,   # current bin
            1,   # next bin
            1,   # day bin
            1,   # night bin
            1,   # moonmode bin
            -1,  # sqm
        ])


        # These shared values are to indicate when the camera is in night/moon modes
        self.night_av = Array('i', [
            1,  # night
            0,  # moonmode
        ])


        self._exposure_class = None
        self._adu = None
        self._exposure = None
        self._gain = None


    @property
    def exposure_class(self):
        return self._exposure_class

    @exposure_class.setter
    def exposure_class(self, exposure_class_str):
        self._exposure_class = getattr(exposure_module, str(exposure_class_str))


    @property
    def adu(self):
        return self._adu

    @adu.setter
    def adu(self, new_adu):
        self._adu = int(new_adu)


    @property
    def exposure(self):
        return self._exposure

    @exposure.setter
    def exposure(self, new_exposure):
        self._exposure = float(new_exposure)


    @property
    def gain(self):
        return self._gain

    @gain.setter
    def gain(self, new_gain):
        self._gain = float(new_gain)



    def main(self):
        exposure_o = self.exposure_class(
            self.config,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
        )


        logger.warning('Current exposure: %0.6f', self.exposure)
        logger.warning('Current gain: %0.6f', self.gain)

        exposure_o.calculate_exposure(self.adu, self.exposure, self.gain)


if __name__ == "__main__":
    ag = AutoGain_Test()

    ag.exposure_class = 'exposure_autogain_exp_prio_db_1_10'
    #ag.exposure_class = 'exposure_autogain_exp_prio_db'
    #ag.exposure_class = 'exposure_autogain_exp_prio_iso'
    #ag.exposure_class = 'exposure_autogain_exp_prio_iso_1_100'

    logger.warning('*** Test increasing exposure only ***')
    ag.adu = 60
    ag.exposure = 10.0
    ag.gain = 10.0
    ag.main()

    logger.warning('*** Test increasing gain only ***')
    ag.adu = 60
    ag.exposure = 15.0
    ag.gain = 10.0
    ag.main()

    logger.warning('*** Test increasing exposure and gain ***')
    ag.adu = 60
    ag.exposure = 14.0
    ag.gain = 10.0
    ag.main()

    logger.warning('*** Test decreasing exposure only ***')
    ag.adu = 90
    ag.exposure = 15.0
    ag.gain = 60.0
    ag.main()

    logger.warning('*** Test decreasing gain only ***')
    ag.adu = 90
    ag.exposure = 10.0
    ag.gain = 60.0
    ag.main()

    logger.warning('*** Test decreasing exposure and gain ***')
    ag.adu = 90
    ag.exposure = 14.0
    ag.gain = 60.0
    ag.main()


    logger.warning('Test test test')
    ag.adu = 190
    ag.exposure = 10.0
    ag.gain = 50.1
    ag.main()


