#!/usr/bin/env python3

#########################################################
# This script looks for failed file transfers (uploads, #
# S3 transfers, and syncapi transfers) and attempts     #
# the transfers again.                                  #
#########################################################

import sys
import argparse
import time
from datetime import datetime
from datetime import timedelta
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


from indi_allsky.flask.models import IndiAllSkyDbCameraTable
from indi_allsky.flask.models import IndiAllSkyDbImageTable
from indi_allsky.flask.models import IndiAllSkyDbVideoTable
from indi_allsky.flask.models import IndiAllSkyDbKeogramTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsTable
from indi_allsky.flask.models import IndiAllSkyDbStarTrailsVideoTable
from indi_allsky.flask.models import IndiAllSkyDbFitsImageTable
from indi_allsky.flask.models import IndiAllSkyDbRawImageTable


from indi_allsky import constants
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask import create_app
from indi_allsky.miscUpload import miscUpload


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

        self.batch_size  = self.threads * 7

        self._upload_images = False
        self._syncapi_images = True

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


        for x in range(self.threads):
            self.upload_worker_list.append({
                'worker'  : None,
                'error_q' : Queue(),
            })


        self._miscUpload = miscUpload(self.config, self.upload_q)


        self._shutdown = False
        self._terminate = False
        signal.signal(signal.SIGINT, self.sigint_handler_main)


    @property
    def upload_images(self):
        return self._upload_images

    @upload_images.setter
    def upload_images(self, new_upload_images):
        self._upload_images = bool(new_upload_images)


    @property
    def syncapi_images(self):
        return self._syncapi_images

    @syncapi_images.setter
    def syncapi_images(self, new_syncapi_images):
        self._syncapi_images = bool(new_syncapi_images)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        logger.warning('The program will exit when the current file transfers complete')

        # set flag for program to stop processes
        self._shutdown = True



    def sync(self):
        next_check_time = time.time()  # start immediately


        with app.app_context():
            status_dict = self._get_entry_status()
            self._report(status_dict)

            time.sleep(5)


            # populate individual entries
            upload_list = list()
            for upload_type in status_dict.keys():
                for table, data in status_dict[upload_type].items():
                    if not data:
                        continue

                    for entry in data[1]:
                        if upload_type == 'upload' and table.__name__ == 'IndiAllSkyDbImageTable':
                            if not self.upload_images:
                                continue

                        if upload_type == 'syncapi' and table.__name__ == 'IndiAllSkyDbImageTable':
                            if not self.syncapi_images:
                                continue


                        upload_list.append({
                            'upload_type' : upload_type,
                            'table'       : table,
                            'entry_id'    : entry.id,  # cannot pass entries to different session
                        })


            logger.info('Entries to upload: %d', len(upload_list))


        while True:
            loop_start_time = time.time()


            if self._shutdown:
                logger.warning('Shutting down')
                self._stopFileUploadWorkers(terminate=self._terminate)
                sys.exit()


            if self.upload_q.qsize() == 0:
                with app.app_context():
                    try:
                        self.addUploadEntries(upload_list)
                    except NoUploadsAvailable:
                        logger.warning('No uploads remaining to process')
                        self._shutdown = True


            # do *NOT* start workers inside of a flask context
            # doing so will cause TLS/SSL problems connecting to databases

            if next_check_time <= loop_start_time:
                # restart worker if it has failed
                self._startFileUploadWorkers()
                next_check_time = loop_start_time + 30


            time.sleep(3)



    def addUploadEntries(self, upload_list):
        if len(upload_list) == 0:
            raise NoUploadsAvailable


        new_uploads = upload_list[:self.batch_size]
        del upload_list[:self.batch_size]

        logger.info('Adding %d upload entries (%d remaining)', len(new_uploads), len(upload_list))


        for x in new_uploads:
            # cannot use entry from different session
            entry = x['table'].query\
                .filter(x['table'].id == x['entry_id']).one()


            if not entry.validateFile():
                logger.error('%s file missing: %s', x['table'].__name__, entry.filename)
                continue


            if x['upload_type'] == 'upload':
                if x['table'].__name__ == 'IndiAllSkyDbImageTable':
                    self._miscUpload.upload_image(entry)
                elif x['table'].__name__ == 'IndiAllSkyDbVideoTable':
                    self._miscUpload.upload_video(entry)
                elif x['table'].__name__ == 'IndiAllSkyDbKeogramTable':
                    self._miscUpload.upload_keogram(entry)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsTable':
                    self._miscUpload.upload_startrail(entry)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsVideoTable':
                    self._miscUpload.upload_startrailvideo(entry)
                else:
                    logger.error('Unknown table: %s', x['table'].__name__)

            elif x['upload_type'] == 's3':
                if x['table'].__name__ == 'IndiAllSkyDbImageTable':
                    image_metadata = {
                        'type'            : constants.IMAGE,
                        'createDate'      : entry.createDate.timestamp(),
                        'exposure'        : entry.exposure,
                        'exp_elapsed'     : entry.exp_elapsed,
                        'gain'            : entry.gain,
                        'binmode'         : entry.binmode,
                        'temp'            : entry.temp,
                        'adu'             : entry.adu,
                        'stable'          : entry.stable,
                        'moonmode'        : entry.moonmode,
                        'moonphase'       : entry.moonphase,
                        'night'           : entry.night,
                        'adu_roi'         : entry.adu_roi,
                        'calibrated'      : entry.calibrated,
                        'sqm'             : entry.sqm,
                        'stars'           : entry.stars,
                        'detections'      : entry.detections,
                        'kpindex'         : entry.kpindex,
                        'ovation_max'     : entry.ovation_max,
                        'smoke_rating'    : entry.smoke_rating,
                        'exclude'         : entry.exclude,
                        'width'           : entry.width,
                        'height'          : entry.height,
                        'process_elapsed' : entry.process_elapsed,
                        'camera_uuid'     : entry.camera.uuid,
                    }

                    if entry.data:
                        image_metadata['data'] = dict(entry.data)
                    else:
                        image_metadata['data'] = dict()

                    self._miscUpload.s3_upload_image(entry, image_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbVideoTable':
                    video_metadata = {
                        'type'          : constants.VIDEO,
                        'createDate'    : entry.createDate.timestamp(),
                        'dayDate'       : entry.dayDate.strftime('%Y%m%d'),
                        'night'         : entry.night,
                        'width'         : entry.width,
                        'height'        : entry.height,
                        'camera_uuid'   : entry.camera.uuid,
                    }

                    if entry.data:
                        video_metadata['data'] = dict(entry.data)
                    else:
                        video_metadata['data'] = dict()

                    self._miscUpload.s3_upload_video(entry, video_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbKeogramTable':
                    keogram_metadata = {
                        'type'       : constants.KEOGRAM,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        keogram_metadata['data'] = dict(entry.data)
                    else:
                        keogram_metadata['data'] = dict()

                    self._miscUpload.s3_upload_keogram(entry, keogram_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsTable':
                    startrail_metadata = {
                        'type'       : constants.STARTRAIL,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        startrail_metadata['data'] = dict(entry.data)
                    else:
                        startrail_metadata['data'] = dict()

                    self._miscUpload.s3_upload_startrail(entry, startrail_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsVideoTable':
                    startrail_video_metadata = {
                        'type'       : constants.STARTRAIL_VIDEO,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        startrail_video_metadata['data'] = dict(entry.data)
                    else:
                        startrail_video_metadata['data'] = dict()

                    self._miscUpload.s3_upload_startrailvideo(entry, startrail_video_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbFitsImageTable':
                    fits_metadata = {
                        'type'       : constants.FITS_IMAGE,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        fits_metadata['data'] = dict(entry.data)
                    else:
                        fits_metadata['data'] = dict()

                    self._miscUpload.s3_upload_fits(entry, fits_metadata)

                elif x['table'].__name__ == 'IndiAllSkyDbRawImageTable':
                    raw_metadata = {
                        'type'       : constants.RAW_IMAGE,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        fits_metadata['data'] = dict(entry.data)
                    else:
                        fits_metadata['data'] = dict()

                    self._miscUpload.s3_upload_raw(entry, raw_metadata)

                else:
                    logger.error('Unknown table: %s', x['table'].__name__)

            elif x['upload_type'] == 'syncapi':
                if x['table'].__name__ == 'IndiAllSkyDbImageTable':
                    image_metadata = {
                        'type'            : constants.IMAGE,
                        'createDate'      : entry.createDate.timestamp(),
                        'exposure'        : entry.exposure,
                        'exp_elapsed'     : entry.exp_elapsed,
                        'gain'            : entry.gain,
                        'binmode'         : entry.binmode,
                        'temp'            : entry.temp,
                        'adu'             : entry.adu,
                        'stable'          : entry.stable,
                        'moonmode'        : entry.moonmode,
                        'moonphase'       : entry.moonphase,
                        'night'           : entry.night,
                        'adu_roi'         : entry.adu_roi,
                        'calibrated'      : entry.calibrated,
                        'sqm'             : entry.sqm,
                        'stars'           : entry.stars,
                        'detections'      : entry.detections,
                        'kpindex'         : entry.kpindex,
                        'ovation_max'     : entry.ovation_max,
                        'smoke_rating'    : entry.smoke_rating,
                        'exclude'         : entry.exclude,
                        'width'           : entry.width,
                        'height'          : entry.height,
                        'process_elapsed' : entry.process_elapsed,
                        'camera_uuid'     : entry.camera.uuid,
                    }

                    if entry.data:
                        image_metadata['data'] = dict(entry.data)
                    else:
                        image_metadata['data'] = dict()

                    self._miscUpload.syncapi_image(entry, image_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbVideoTable':
                    video_metadata = {
                        'type'          : constants.VIDEO,
                        'createDate'    : entry.createDate.timestamp(),
                        'dayDate'       : entry.dayDate.strftime('%Y%m%d'),
                        'night'         : entry.night,
                        'width'         : entry.width,
                        'height'        : entry.height,
                        'camera_uuid'   : entry.camera.uuid,
                    }

                    if entry.data:
                        video_metadata['data'] = dict(entry.data)
                    else:
                        video_metadata['data'] = dict()

                    self._miscUpload.syncapi_video(entry, video_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbKeogramTable':
                    keogram_metadata = {
                        'type'       : constants.KEOGRAM,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        keogram_metadata['data'] = dict(entry.data)
                    else:
                        keogram_metadata['data'] = dict()

                    self._miscUpload.syncapi_keogram(entry, keogram_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsTable':
                    startrail_metadata = {
                        'type'       : constants.STARTRAIL,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        startrail_metadata['data'] = dict(entry.data)
                    else:
                        startrail_metadata['data'] = dict()

                    self._miscUpload.syncapi_startrail(entry, startrail_metadata)
                elif x['table'].__name__ == 'IndiAllSkyDbStarTrailsVideoTable':
                    startrail_video_metadata = {
                        'type'       : constants.STARTRAIL_VIDEO,
                        'createDate' : entry.createDate.timestamp(),
                        'dayDate'    : entry.dayDate.strftime('%Y%m%d'),
                        'night'      : entry.night,
                        'width'      : entry.width,
                        'height'     : entry.height,
                        'camera_uuid': entry.camera.uuid,
                    }

                    if entry.data:
                        startrail_video_metadata['data'] = dict(entry.data)
                    else:
                        startrail_video_metadata['data'] = dict()

                    self._miscUpload.syncapi_startrailvideo(entry, startrail_video_metadata)
                else:
                    logger.error('Unknown table: %s', x['table'].__name__)

            else:
                logger.error('Unknown upload type: %s', x['upload_type'])


    def report(self):
        with app.app_context():
            status_dict = self._get_entry_status()

            self._report(status_dict)


        if not self.upload_images:
            logger.warning('Image upload is disabled by default')


    def _report(self, status_dict):
        ptable = PrettyTable()
        ptable.field_names = ['Type', 'Table', 'Uploaded', 'Missing']

        for upload_type in status_dict.keys():
            for table, data in status_dict[upload_type].items():
                if not data:
                    ptable.add_row([upload_type, table.__name__, '-', '-'])
                    continue

                ptable.add_row([upload_type, table.__name__, data[0].count(), data[1].count()])


        print(ptable)



    def _get_entry_status(self):
        status_dict = {
            'upload'  : dict(),
            's3'      : dict(),
            'syncapi' : dict(),
        }

        # upload
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
                status_dict['upload'][table[0]] = [uploaded, not_uploaded]
            else:
                logger.info('%s uploading disabled', table[0].__name__)
                status_dict['upload'][table[0]] = None


        if self.upload_images:
            upload_image = int(self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'))
            if upload_image:
                uploaded = self._get_uploaded(IndiAllSkyDbImageTable, upload_image, state=True)
                not_uploaded = self._get_uploaded(IndiAllSkyDbImageTable, upload_image, state=False)
                status_dict['upload'][IndiAllSkyDbImageTable] = [uploaded, not_uploaded]
            else:
                logger.info('%s uploading disabled', IndiAllSkyDbImageTable.__name__)
                status_dict['upload'][IndiAllSkyDbImageTable] = None



        # s3
        s3_table_list = [
            IndiAllSkyDbVideoTable,
            IndiAllSkyDbKeogramTable,
            IndiAllSkyDbStarTrailsTable,
            IndiAllSkyDbStarTrailsVideoTable,
            IndiAllSkyDbImageTable,
        ]
        for table in s3_table_list:
            # s3
            if self.config.get('S3UPLOAD', {}).get('ENABLE'):
                s3_entries = self._get_s3(table, state=True)
                not_s3_entries = self._get_s3(table, state=False)
                status_dict['s3'][table] = [s3_entries, not_s3_entries]
            else:
                logger.info('S3 uploading disabled (%s)', table.__name__)
                status_dict['s3'][table] = None


        s3_upload_fits = self.config.get('S3UPLOAD', {}).get('UPLOAD_FITS')
        if s3_upload_fits:
            s3_entries_fits = self._get_s3(IndiAllSkyDbFitsImageTable, state=True)
            not_s3_entries_fits = self._get_s3(IndiAllSkyDbFitsImageTable, state=False)
            status_dict['s3'][IndiAllSkyDbFitsImageTable] = [s3_entries_fits, not_s3_entries_fits]
        else:
            logger.info('S3 uploading disabled (%s)', IndiAllSkyDbFitsImageTable.__name__)
            status_dict['s3'][IndiAllSkyDbFitsImageTable] = None


        s3_upload_raw = self.config.get('S3UPLOAD', {}).get('UPLOAD_RAW')
        if s3_upload_raw:
            s3_entries_raw = self._get_s3(IndiAllSkyDbRawImageTable, state=True)
            not_s3_entries_raw = self._get_s3(IndiAllSkyDbRawImageTable, state=False)
            status_dict['s3'][IndiAllSkyDbRawImageTable] = [s3_entries_raw, not_s3_entries_raw]
        else:
            logger.info('S3 uploading disabled (%s)', IndiAllSkyDbRawImageTable.__name__)
            status_dict['s3'][IndiAllSkyDbRawImageTable] = None


        # syncapi
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
                status_dict['syncapi'][table] = [syncapi_entries, not_syncapi_entries]
            else:
                logger.info('syncapi disabled (%s)', table.__name__)
                status_dict['syncapi'][table] = None


        if self.config.get('SYNCAPI', {}).get('ENABLE'):
            syncapi_image = int(self.config.get('SYNCAPI', {}).get('UPLOAD_IMAGE'))
            if syncapi_image:
                syncapi_entries = self._get_syncapi(IndiAllSkyDbImageTable, syncapi_image, state=True)
                not_syncapi_entries = self._get_syncapi(IndiAllSkyDbImageTable, syncapi_image, state=False)
                status_dict['syncapi'][IndiAllSkyDbImageTable] = [syncapi_entries, not_syncapi_entries]
            else:
                logger.info('syncapi disabled (%s)', IndiAllSkyDbImageTable.__name__)
                status_dict['syncapi'][IndiAllSkyDbImageTable] = None
        else:
            logger.info('syncapi disabled (%s)', IndiAllSkyDbImageTable.__name__)
            status_dict['syncapi'][IndiAllSkyDbImageTable] = None


        return status_dict


    def _get_uploaded(self, table, mod, state=True):
        now = datetime.now()
        now_minus_10m = now - timedelta(minutes=10)

        if state:
            uploaded = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.uploaded == sa_true())\
                .filter(table.id % mod == 0)\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())
        else:
            uploaded = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.uploaded == sa_false())\
                .filter(table.id % mod == 0)\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())

        return uploaded


    def _get_s3(self, table, state=True):
        now = datetime.now()
        now_minus_10m = now - timedelta(minutes=10)

        if state:
            s3 = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.s3_key != sa_null())\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())
        else:
            s3 = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.s3_key == sa_null())\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())

        return s3


    def _get_syncapi(self, table, mod, state=True):
        now = datetime.now()
        now_minus_10m = now - timedelta(minutes=10)

        if state:
            syncapi = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.sync_id != sa_null())\
                .filter(table.id % mod == 0)\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())
        else:
            syncapi = table.query\
                .join(table.camera)\
                .filter(IndiAllSkyDbCameraTable.hidden == sa_false())\
                .filter(table.sync_id == sa_null())\
                .filter(table.id % mod == 0)\
                .filter(table.createDate <= now_minus_10m)\
                .order_by(table.createDate.desc())

        return syncapi



    def _startFileUploadWorkers(self):
        for upload_worker_dict in self.upload_worker_list:
            self._fileUploadWorkerStart(upload_worker_dict)


    def _fileUploadWorkerStart(self, uw_dict):
        from indi_allsky.uploader import FileUploader

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



class NoUploadsAvailable(Exception):
    pass


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
        default=1
    )

    argparser.add_argument(
        '--no-upload-images',
        help='disable image uploading (default)',
        dest='upload_images',
        action='store_false',
    )
    argparser.add_argument(
        '--upload-images',
        help='enable image uploading',
        dest='upload_images',
        action='store_true',
    )
    argparser.set_defaults(upload_images=False)

    argparser.add_argument(
        '--no-syncapi-images',
        help='disable syncapi for images',
        dest='syncapi_images',
        action='store_false',
    )
    argparser.add_argument(
        '--syncapi-images',
        help='enable syncapi for images (default)',
        dest='syncapi_images',
        action='store_true',
    )
    argparser.set_defaults(syncapi_images=True)


    args = argparser.parse_args()

    us = UploadSync(args.threads)
    us.upload_images = args.upload_images
    us.syncapi_images = args.syncapi_images

    action_func = getattr(us, args.action)
    action_func()

