#!/usr/bin/env python3
#####################################################################
# This script adds the indi-allsky virtualenv to the sys.path for   #
# the current user                                                  #
#####################################################################


import sys
import site
import io
from pathlib import Path
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


class SetupUserSitePth(object):

    def main(self):
        indi_allsky_dir = Path(__file__).parent.parent.absolute()
        logger.info('indi-allsky folder: %s', indi_allsky_dir)


        venv_p = Path(__file__).parent.parent.joinpath('virtualenv', 'indi-allsky').absolute()
        if not venv_p.is_dir():
            logger.error('indi-allsky virtualenv is not created')
            sys.exit(1)

        #logger.info('Virtualenv folder: %s', venv_p)


        venv_site_packages_p = venv_p.joinpath('lib', 'python{0:d}.{1:d}'.format(*sys.version_info), 'site-packages')
        if not venv_site_packages_p.is_dir():
            logger.error('Cannot find virtualenv site-package folder')
            sys.exit()  # normal exit


        user_site_p = Path(site.getusersitepackages())
        logger.info('User Site Package Dir: %s', user_site_p)


        if not user_site_p.is_dir():
            user_site_p.mkdir(parents=True)


        pth_file = user_site_p.joinpath('indi-allsky.pth')
        logger.info('Creating pth: %s', pth_file)

        with io.open(pth_file, 'w') as f_pth:
            f_pth.write(str(venv_site_packages_p))


        pth_file.chmod(0o644)


if __name__ == "__main__":
    SetupUserSitePth().main()
