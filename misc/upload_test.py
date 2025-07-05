#!/usr/bin/env python3
#########################################################
# This script validates the file transfer configuration #
# is valid and working                                  #
#########################################################


import sys
from pathlib import Path
import argparse
import time
import queue
import logging


from multiprocessing import Queue
from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))


from indi_allsky import constants
from indi_allsky.miscUpload import miscUpload
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.flask.models import IndiAllSkyDbImageTable


# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class TestUpload(object):

    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self.upload_q = Queue()
        self.upload_worker_idx = 0


        # we only need 1
        self.upload_worker_list = [{
            'worker'  : None,
            'error_q' : Queue(),
        }]

        self._miscUpload = None


    def filetransfer(self):
        logger.warning('Testing file transfer')


        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'):
            logger.error('Image uploads are disabled')
            sys.exit(1)


        self._startFileUploadWorkers()
        #time.sleep(1.0)


        self.config['FILETRANSFER']['UPLOAD_IMAGE'] = 1  # force enable image uploads
        self._miscUpload = miscUpload(
            self.config,
            self.upload_q,
            None,  # night_v not needed
        )


        try:
            image_entry = IndiAllSkyDbImageTable.query\
                .order_by(IndiAllSkyDbImageTable.createDate.desc())\
                .limit(1)\
                .one()
        except NoResultFound:
            logger.error('No image found to test transfer')
            sys.exit(1)


        logger.info('Testing Image: %s', image_entry.filename)
        time.sleep(1.0)


        self._miscUpload.upload_image(image_entry)


        time.sleep(5)


        self._stopFileUploadWorkers()


    def s3(self):
        logger.warning('Testing S3 transfer')


        if not self.config.get('S3UPLOAD', {}).get('ENABLE'):
            logger.error('S3 uploading disabled')
            sys.exit(1)


        self._startFileUploadWorkers()
        #time.sleep(1.0)


        self.config['S3UPLOAD']['ENABLE'] = True  # force enable image uploads
        self._miscUpload = miscUpload(
            self.config,
            self.upload_q,
            None,  # night_v not needed
        )


        try:
            image_entry = IndiAllSkyDbImageTable.query\
                .order_by(IndiAllSkyDbImageTable.createDate.desc())\
                .limit(1)\
                .one()
        except NoResultFound:
            logger.error('No image found to test Object Storage transfer')
            sys.exit(1)


        logger.info('Testing Image: %s', image_entry.filename)
        time.sleep(1.0)


        image_metadata = {
            'type'            : constants.IMAGE,
            'createDate'      : int(image_entry.createDate.timestamp()),  # data for syncapi
            'dayDate'         : image_entry.dayDate.strftime('%Y%m%d'),
            'exposure'        : image_entry.exposure,
            'exp_elapsed'     : image_entry.exp_elapsed,
            'gain'            : image_entry.gain,
            'binmode'         : image_entry.binmode,
            'temp'            : image_entry.temp,
            'calibrated'      : image_entry.calibrated,
            'adu'             : image_entry.adu,
            'stable'          : image_entry.stable,
            'sqm'             : image_entry.sqm,
            'stars'           : image_entry.stars,
            'detections'      : image_entry.detections,
            'process_elapsed' : image_entry.process_elapsed,
            'height'          : image_entry.height,
            'width'           : image_entry.width,
            'kpindex'         : image_entry.kpindex,
            'ovation_max'     : image_entry.ovation_max,
            'smoke_rating'    : image_entry.smoke_rating,
            'exclude'         : image_entry.exclude,
            'night'           : image_entry.night,
            'moonmode'        : image_entry.moonmode,
            'moonphase'       : image_entry.moonphase,
            'adu_roi'         : image_entry.adu_roi,
            'utc_offset'      : image_entry.createDate.astimezone().utcoffset().total_seconds(),
            'camera_uuid'     : image_entry.camera.uuid,
            'data'            : dict(image_entry.data),  # data for syncapi
        }

        self._miscUpload.s3_upload_image(image_entry, image_metadata)


        time.sleep(5)


        self._stopFileUploadWorkers()


    def syncapi(self):
        logger.warning('Testing SyncAPI transfer')


        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            logger.error('SyncAPI disabled')
            sys.exit(1)


        self._startFileUploadWorkers()
        #time.sleep(1.0)


        self.config['SYNCAPI']['ENABLE'] = True  # force enable syncapi
        self.config['SYNCAPI']['UPLOAD_IMAGE'] = 1  # upload every image
        self._miscUpload = miscUpload(
            self.config,
            self.upload_q,
            None,  # night_v not needed
        )


        try:
            image_entry = IndiAllSkyDbImageTable.query\
                .order_by(IndiAllSkyDbImageTable.createDate.desc())\
                .limit(1)\
                .one()
        except NoResultFound:
            logger.error('No image found to test SyncAPI transfer')
            sys.exit(1)


        logger.info('Testing Image: %s', image_entry.filename)
        time.sleep(1.0)


        image_metadata = {
            'type'            : constants.IMAGE,
            'createDate'      : int(image_entry.createDate.timestamp()),  # data for syncapi
            'dayDate'         : image_entry.dayDate.strftime('%Y%m%d'),
            'exposure'        : image_entry.exposure,
            'exp_elapsed'     : image_entry.exp_elapsed,
            'gain'            : image_entry.gain,
            'binmode'         : image_entry.binmode,
            'temp'            : image_entry.temp,
            'calibrated'      : image_entry.calibrated,
            'adu'             : image_entry.adu,
            'stable'          : image_entry.stable,
            'sqm'             : image_entry.sqm,
            'stars'           : image_entry.stars,
            'detections'      : image_entry.detections,
            'process_elapsed' : image_entry.process_elapsed,
            'height'          : image_entry.height,
            'width'           : image_entry.width,
            'kpindex'         : image_entry.kpindex,
            'ovation_max'     : image_entry.ovation_max,
            'smoke_rating'    : image_entry.smoke_rating,
            'exclude'         : image_entry.exclude,
            'night'           : image_entry.night,
            'moonmode'        : image_entry.moonmode,
            'moonphase'       : image_entry.moonphase,
            'adu_roi'         : image_entry.adu_roi,
            'utc_offset'      : image_entry.createDate.astimezone().utcoffset().total_seconds(),
            'camera_uuid'     : image_entry.camera.uuid,
            'data'            : dict(image_entry.data),  # data for syncapi
        }

        self._miscUpload.syncapi_image(image_entry, image_metadata)


        time.sleep(5)


        self._stopFileUploadWorkers()


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
            #self.upload_q.put({'stop' : True})
            upload_worker_dict['worker'].stop()


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
        'type',
        choices=('filetransfer', 's3', 'syncapi'),
        help='file transfer type',
        type=str,
    )

    args = argparser.parse_args()


    tu = TestUpload()

    action_func = getattr(tu, args.type)
    action_func()
