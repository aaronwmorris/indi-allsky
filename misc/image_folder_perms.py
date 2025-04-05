#!/usr/bin/env python3

import os
import sys
import site
from pathlib import Path
import logging


if 'VIRTUAL_ENV' not in os.environ:
    # dynamically initialize virtualenv
    venv_p = Path(__file__).parent.parent.joinpath('virtualenv', 'indi-allsky').absolute()

    if venv_p.is_dir():
        site.addsitedir(str(venv_p.joinpath('lib', 'python{0:d}.{1:d}'.format(*sys.version_info), 'site-packages')))
        site.PREFIXES = [str(venv_p)]


from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import create_app


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class ImageFolderPermissions(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()



    def main(self):
        folder = self.image_dir

        while True:
            logger.info('Folder: %s', folder)
            logger.info(' Owner: %s', folder.owner())
            logger.info(' Group, %s', folder.group())
            logger.info(' Mode: %s', oct(folder.stat().st_mode))

            folder = folder.parent
            if folder == Path('/'):
                break


if __name__ == "__main__":
    ImageFolderPermissions().main()

