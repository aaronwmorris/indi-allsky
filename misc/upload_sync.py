#!/usr/bin/env python3

### THIS SCRIPT IS NOT COMPLETE ###

import sys
import argparse
import time
from prettytable import PrettyTable
from pathlib import Path
import signal
import logging

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import true as sa_true
from sqlalchemy.sql.expression import false as sa_false
from sqlalchemy.sql.expression import null as sa_null

import queue
from multiprocessing import Queue

sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable


from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import create_app
from indi_allsky.uploader import FileUploader


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() #%(lineno)d: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


app = create_app()


class UploadSync(object):

    def __init__(self, threads):
        self.threads = int(threads)

        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
                #logger.info('Loaded config id: %d', self._config_obj.config_id)
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

            self.config = self._config_obj.config


        self.upload_q = Queue()
        self.upload_worker_list = []
        self.upload_worker_idx = 0


        for x in range(self.config.get('UPLOAD_WORKERS', 1)):
            self.upload_worker_list.append({
                'worker'  : None,
                'error_q' : Queue(),
            })


        self._shutdown = False
        self._terminate = False
        signal.signal(signal.SIGINT, self.sigint_handler_main)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True



    def sync(self):
        next_check_time = time.time()  # start immediately


        while True:
            loop_start_time = time.time()


            if self._shutdown:
                logger.warning('Shutting down')
                self._stopFileUploadWorkers(terminate=self._terminate)
                sys.exit()


            # do *NOT* start workers inside of a flask context
            # doing so will cause TLS/SSL problems connecting to databases

            if next_check_time <= loop_start_time:
                # restart worker if it has failed
                self._startFileUploadWorkers()
                next_check_time = loop_start_time + 30


            time.sleep(5.0)




    def report(self):
        with app.app_context():
            self._report()


    def _report(self):
        table = PrettyTable()
        table.field_names = ['Type', 'Table', 'Uploaded', 'Missing']


        type_dict = {
            'upload'  : dict(),
            's3'      : dict(),
            'syncapi' : dict(),
        }

        # upload
        upload_image = int(self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'))
        if upload_image:
            uploaded = self._get_uploaded(IndiAllSkyDbImageTable, upload_image, state=True)
            not_uploaded = self._get_uploaded(IndiAllSkyDbImageTable, upload_image, state=False)
            type_dict['upload'][IndiAllSkyDbImageTable] = [uploaded, not_uploaded]
        else:
            logger.info('%s uploading disabled', IndiAllSkyDbImageTable.__name__)
            type_dict['upload'][IndiAllSkyDbImageTable] = None


        upload_table_list = [
            [IndiAllSkyDbVideoTable, 'UPLOAD_VIDEO'],
            [IndiAllSkyDbKeogramTable, 'UPLOAD_KEOGRAM'],
            [IndiAllSkyDbStarTrailsTable, 'UPLOAD_STARTRAIL'],
            [IndiAllSkyDbStarTrailsVideoTable, 'UPLOAD_VIDEO'],
        ]

        for table in upload_table_list:
            upload = self.config.get('FILETRANSFER', {}).get(table[1])
            if upload:
                uploaded = self._get_uploaded(table[0], 1, state=True)
                not_uploaded = self._get_uploaded(table[0], 1, state=False)
                type_dict['upload'][table[0]] = [uploaded, not_uploaded]
            else:
                logger.info('%s uploading disabled', table[0].__name__)
                type_dict['upload'][table[0]] = None




        # s3
        s3_table_list = [
            IndiAllSkyDbImageTable,
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
        ]
        for table in s3_table_list:
            # s3
            if self.config.get('S3UPLOAD', {}).get('ENABLE'):
                s3_entries = self._get_s3(table, state=True)
                not_s3_entries = self._get_s3(table, state=False)
                type_dict['s3'][table] = [s3_entries, not_s3_entries]
            else:
                logger.info('S3 uploading disabled (%s)', table.__name__)
                type_dict['s3'][table] = None




        # syncapi
        if self.config.get('SYNCAPI', {}).get('ENABLE'):
            syncapi_image = int(self.config.get('SYNCAPI', {}).get('UPLOAD_IMAGE'))
            if syncapi_image:
                syncapi_entries = self._get_syncapi(IndiAllSkyDbImageTable, syncapi_image, state=True)
                not_syncapi_entries = self._get_syncapi(IndiAllSkyDbImageTable, syncapi_image, state=False)
                type_dict['syncapi'][IndiAllSkyDbImageTable] = [syncapi_entries, not_syncapi_entries]
            else:
                logger.info('syncapi disabled (%s)', IndiAllSkyDbImageTable.__name__)
                type_dict['syncapi'][IndiAllSkyDbImageTable] = None
        else:
            logger.info('syncapi disabled (%s)', IndiAllSkyDbImageTable.__name__)
            type_dict['syncapi'][IndiAllSkyDbImageTable] = None



        syncapi_table_list = [
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
        ]
        for table in syncapi_table_list:
            if self.config.get('SYNCAPI', {}).get('ENABLE'):
                syncapi_entries = self._get_syncapi(table, 1, state=True)
                not_syncapi_entries = self._get_syncapi(table, 1, state=False)
                type_dict['syncapi'][table] = [syncapi_entries, not_syncapi_entries]
            else:
                logger.info('syncapi disabled (%s)', table.__name__)
                type_dict['syncapi'][table] = None



        #print(table)


    def _get_uploaded(self, table, mod, state=True):
        if state:
            uploaded = table.query\
                .filter(table.uploaded == sa_true())\
                .filter(table.id % mod == 0)
        else:
            uploaded = table.query\
                .filter(table.uploaded == sa_false())\
                .filter(table.id % mod == 0)

        return uploaded


    def _get_s3(self, table, state=True):
        if state:
            s3 = table.query\
                .filter(table.s3_key != sa_null())
        else:
            s3 = table.query\
                .filter(table.s3_key == sa_null())

        return s3


    def _get_syncapi(self, table, mod, state=True):
        if state:
            syncapi = table.query\
                .filter(table.sync_id != sa_null())\
                .filter(table.id % mod == 0)
        else:
            syncapi = table.query\
                .filter(table.sync_id == sa_null())\
                .filter(table.id % mod == 0)

        return syncapi



    def _startFileUploadWorkers(self):
        for upload_worker_dict in self.upload_worker_list:
            self._fileUploadWorkerStart(upload_worker_dict)


    def _fileUploadWorkerStart(self, uw_dict):
        if uw_dict['worker']:
            if uw_dict['worker'].is_alive():
                return


            try:
                upload_error, upload_traceback = uw_dict['error_q'].get_nowait()
                for line in upload_traceback.split('\n'):
                    logger.error('Upload worker exception: %s', line)
            except queue.Empty:
                pass


        self.upload_worker_idx += 1

        logger.info('Starting FileUploader process %d', self.upload_worker_idx)
        uw_dict['worker'] = FileUploader(
            self.upload_worker_idx,
            self.config,
            uw_dict['error_q'],
            self.upload_q,
        )

        uw_dict['worker'].start()


    def _stopFileUploadWorkers(self, terminate=False):
        active_worker_list = list()
        for upload_worker_dict in self.upload_worker_list:
            if not upload_worker_dict['worker']:
                continue

            if not upload_worker_dict['worker'].is_alive():
                continue

            active_worker_list.append(upload_worker_dict)

            # need to put the stops in the queue before waiting on workers to join
            self.upload_q.put({'stop' : True})


        for upload_worker_dict in active_worker_list:
            self._fileUploadWorkerStop(upload_worker_dict, terminate=terminate)


    def _fileUploadWorkerStop(self, uw_dict, terminate=False):
        if terminate:
            logger.info('Terminating FileUploadWorker process')
            uw_dict['worker'].terminate()

        logger.info('Stopping FileUploadWorker process')

        uw_dict['worker'].join()




if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        type=str,
        choices=(
            'sync',
            'report',
        ),
    )
    argparser.add_argument(
        '--threads',
        '-t',
        help='threads',
        type=int,
        default=2
    )


    args = argparser.parse_args()

    us = UploadSync(args.threads)

    action_func = getattr(us, args.action)
    action_func()

