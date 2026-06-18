#!/usr/bin/env python3


import sys
from pathlib import Path
import logging

from multiprocessing import Array


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.config import IndiAllSkyConfig
from indi_allsky import constants
from indi_allsky import exposure as exposure_module

from indi_allsky.flask import create_app
from sqlalchemy.orm.exc import NoResultFound


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


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
            15.0,  # current exposure
            -1.0,  # next exposure
            1.0,   # exposure delta
            0.0,   # night minimum
            0.0,   # day minimum
            15.0,  # maximum
            -1.0,  # sqm
        ])


        self.gain_av = Array('f', [
            10.0,   # current gain
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



    def main(self):
        exposure_class_str = self.config.get('CCD_CONFIG', {}).get('EXPOSURE_CLASSNAME')
        if exposure_class_str:
            exposure_class = getattr(exposure_module, exposure_class_str)
        else:
            exposure_class = getattr(exposure_module, 'exposure_basic')


        self.exposure_o = exposure_class(
            self.config,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
        )


        adu = 60
        exposure = float(self.exposure_av[constants.EXPOSURE_CURRENT])
        gain = float(self.gain_av[constants.GAIN_CURRENT])


        logger.warning('Current exposure: %0.6f', exposure)

        adu, adu_average = self.exposure_o.calculate_exposure(adu, exposure, gain)


if __name__ == "__main__":
    ag = AutoGain_Test()
    ag.main()
