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
#from sqlalchemy.sql.expression import true as sa_true
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
        table.field_names = ['Type', 'Uploaded', 'Missing']


        # upload
        upload_image = int(self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'))
        if upload_image:
            not_uploaded_images = self._get_not_uploaded(IndiAllSkyDbImageTable, upload_image)
            logger.warning('Images not uploaded: %d', not_uploaded_images.count())
        else:
            logger.info('Image uploading disabled')


        # s3
        if self.config.get('S3UPLOAD', {}).get('ENABLE'):
            not_s3_images = self._get_not_s3(IndiAllSkyDbImageTable)
            logger.warning('Images not in S3: %d', not_s3_images.count())
        else:
            logger.info('S3 uploading disabled')


        # syncapi
        if self.config.get('SYNCAPI', {}).get('ENABLE'):
            syncapi_image = int(self.config.get('SYNCAPI', {}).get('UPLOAD_IMAGE'))
            if syncapi_image:
                not_syncapi_images = self._get_not_syncapi(IndiAllSkyDbImageTable, syncapi_image)
                logger.warning('Images not synced: %d', not_syncapi_images.count())
            else:
                logger.info('Image syncing disabled')
        else:
            logger.info('Image syncapi disabled')



        table_list = [
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
        ]
        for table in table_list:
            # s3
            if self.config.get('S3UPLOAD', {}).get('ENABLE'):
                not_s3_entries = self._get_not_s3(table)
                logger.warning('%s not in S3: %d', table.__name__, not_s3_entries.count())
            else:
                logger.info('S3 uploading disabled')


            if self.config.get('SYNCAPI', {}).get('ENABLE'):
                not_syncapi_entries = self._get_not_syncapi(table, 1)
                logger.warning('%s not synced: %d', table.__name__, not_syncapi_entries.count())
            else:
                logger.info('syncapi disabled')





        #print(table)


    def _get_not_uploaded(self, table, mod):
        not_uploaded = table.query\
            .filter(table.uploaded == sa_false())\
            .filter(table.id % mod == 0)

        return not_uploaded


    def _get_not_s3(self, table):
        not_s3 = table.query\
            .filter(table.s3_key == sa_null())

        return not_s3


    def _get_not_syncapi(self, table, mod):
        not_syncapi = table.query\
            .filter(table.sync_id == sa_null())\
            .filter(table.id % mod == 0)

        return not_syncapi



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

