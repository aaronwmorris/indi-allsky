
import time
from datetime import datetime
from pathlib import Path
import subprocess
import sqlite3
import logging

from .flask import db
from .flask.miscDb import miscDb

from .exceptions import BackupFailure


logger = logging.getLogger('indi_allsky')


class IndiAllskyDatabaseBackup(object):

    def __init__(self, config, skip_frames=0):
        self.config = config

        self._miscDb = miscDb(self.config)

        self.backup_folder = Path('/var/lib/indi-allsky/backup')


    def db_backup(self):
        now_time = time.time()

        # immediately set timestamp so if it fails, it will not run immediately again
        self._miscDb.setState('BACKUP_DB_TS', int(now_time))


        now = datetime.now()
        backup_file_p = self.backup_folder.joinpath('backup_indi-allsky_{0:%Y%m%d_%H%M%S}.sqlite'.format(now))
        logger.warning('Backing up database to %s.gz', backup_file_p)


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
            raise BackupFailure('Backup compress failed')

