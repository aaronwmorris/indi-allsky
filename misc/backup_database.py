#!/usr/bin/env python3

import os
import sys
import site
from pathlib import Path


if 'VIRTUAL_ENV' not in os.environ:
    # dynamically initialize virtualenv
    venv_p = Path(__file__).parent.parent.joinpath('virtualenv', 'indi-allsky').absolute()

    if venv_p.is_dir():
        sys.path.insert(0, str(venv_p.joinpath('lib', 'python{0:d}.{1:d}'.format(*sys.version_info), 'site-packages')))
        site.addsitedir(str(venv_p.joinpath('lib', 'python{0:d}.{1:d}'.format(*sys.version_info), 'site-packages')))
        site.PREFIXES = [str(venv_p)]


import time
import logging

from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.backup import IndiAllskyDatabaseBackup
from indi_allsky.exceptions import BackupFailure

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


class BackupDatabase(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


    def main(self):
        if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            logger.error('Only sqlite backups are supported')
            sys.exit(1)


        backup_start = time.time()

        backup = IndiAllskyDatabaseBackup(self.config)


        try:
            backup.db_backup()
        except BackupFailure as e:
            logger.error('Backup compress failed: %s', str(e))
            sys.exit(1)


        backup_elapsed_s = time.time() - backup_start
        logger.info('Backup completed in %0.2fs', backup_elapsed_s)


if __name__ == "__main__":
    BackupDatabase().main()
