
import time
from datetime import datetime
from pathlib import Path
import subprocess
import psutil
import sqlite3
import logging

from .flask import db
from .flask.miscDb import miscDb

from .exceptions import BackupFailure


logger = logging.getLogger('indi_allsky')


class IndiAllskyDatabaseBackup(object):

    # maintain at least this many backups
    keep_backups = 7


    def __init__(self, config, skip_frames=0):
        self.config = config

        self._miscDb = miscDb(self.config)

        self.backup_folder = Path('/var/lib/indi-allsky/backup')


    def db_backup(self):
        self.checkAvailableSpace()


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


        self.expireBackups()


        return '{0:s}.gz'.format(str(backup_file_p))


    def expireBackups(self):
        backup_list = list()

        self._getFolderFilesByExt(self.backup_folder, backup_list, extension_list=['gz', 'sqlite'])

        backup_list_ordered = sorted(backup_list, key=lambda p: p.stat().st_mtime, reverse=True)


        remove_backups = backup_list_ordered[self.keep_backups:]


        for b in remove_backups:
            logger.warning('Remove backup: %s', b)
            b.unlink()


    def checkAvailableSpace(self):
        fs_list = psutil.disk_partitions(all=True)

        for fs in fs_list:
            if fs.mountpoint not in ('/', '/var'):
                continue

            try:
                disk_usage = psutil.disk_usage(fs.mountpoint)
            except PermissionError as e:
                logger.error('PermissionError: %s', str(e))
                continue


            fs_free_mb = disk_usage.total / 1024.0 / 1024.0

            if fs_free_mb < 1000:
                raise BackupFailure('Not enough available filesystem space on {0:s} filesystem'.format(fs.mountpoint))


    def _getFolderFilesByExt(self, folder, file_list, extension_list=['gz']):
        #logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self._getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion

