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
from datetime import datetime
import subprocess
import sqlite3
import logging


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import db
from indi_allsky.flask import create_app

logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


# setup flask context for db access
app = create_app()
app.app_context().push()


LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class BackupDatabase(object):

    def main(self):
        if not app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            logger.error('Only sqlite backups are supported')
            sys.exit(1)


        now = datetime.now()
        backup_file_p = Path('/var/lib/indi-allsky/backup/backup_indi-allsky_{0:%Y%m%d_%H%M%S}.sqlite'.format(now))
        logger.warning('Backing up database to %s.gz', backup_file_p)


        backup_start = time.time()

        backup_conn = sqlite3.connect(str(backup_file_p))

        raw_connection = db.engine.raw_connection()
        raw_connection.backup(backup_conn)

        raw_connection.close()
        backup_conn.close()


        backup_file_p.chmod(0o640)


        try:
            subprocess.run(
                ('/usr/bin/gzip', str(backup_file_p)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            logger.error('Backup compress failed: %s', str(e))
            sys.exit(1)


        backup_elapsed_s = time.time() - backup_start
        logger.info('Backup completed in %0.2fs', backup_elapsed_s)


if __name__ == "__main__":
    BackupDatabase().main()
