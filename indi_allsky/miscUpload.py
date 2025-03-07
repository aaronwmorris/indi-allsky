from pathlib import Path
from datetime import datetime
import logging

from . import constants

from .flask import db

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbTaskQueueTable

logger = logging.getLogger('indi_allsky')


class miscUpload(object):

    def __init__(
        self,
        config,
        upload_q,
    ):

        self.config = config
        self.upload_q = upload_q


    def upload_image(self, image_entry):
        ### upload images
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_IMAGE'):
            #logger.warning('Image uploading disabled')
            return


        if not image_entry:
            # image was not saved
            return


        image_remain = image_entry.id % int(self.config['FILETRANSFER']['UPLOAD_IMAGE'])
        if image_remain != 0:
            next_image = int(self.config['FILETRANSFER']['UPLOAD_IMAGE']) - image_remain
            logger.info('Next image upload in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
            return


        # Parameters for string formatting
        file_data_list = [
            self.config['IMAGE_FILE_TYPE'],
        ]


        file_data_dict = {
            'timestamp'    : image_entry.createDate,
            'ts'           : image_entry.createDate,  # shortcut
            'day_date'     : image_entry.dayDate,
            'ext'          : Path(image_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : image_entry.camera.uuid,
            'camera_id'    : image_entry.camera.id,
        }


        if image_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_IMAGE_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_IMAGE_NAME'].format(*file_data_list, **file_data_dict)


        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : image_entry.__class__.__name__,
            'id'          : image_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_video(self, video_entry):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_VIDEO'):
            #logger.warning('Video uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : video_entry.dayDate,
            'ext'          : Path(video_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : video_entry.camera.uuid,
            'camera_id'    : video_entry.camera.id,
        }


        if video_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_VIDEO_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_VIDEO_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : video_entry.__class__.__name__,
            'id'          : video_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_mini_video(self, video_entry):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_MINI_VIDEO'):
            #logger.warning('Video uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : video_entry.dayDate,
            'ext'          : Path(video_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : video_entry.camera.uuid,
            'camera_id'    : video_entry.camera.id,
        }


        if video_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_MINI_VIDEO_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_MINI_VIDEO_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : video_entry.__class__.__name__,
            'id'          : video_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_panorama_video(self, video_entry):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_PANORAMA_VIDEO'):
            #logger.warning('Video uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : video_entry.dayDate,
            'ext'          : Path(video_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : video_entry.camera.uuid,
            'camera_id'    : video_entry.camera.id,
        }


        if video_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_PANORAMA_VIDEO_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_PANORAMA_VIDEO_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : video_entry.__class__.__name__,
            'id'          : video_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_keogram(self, keogram_entry):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_KEOGRAM'):
            #logger.warning('Keogram uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : keogram_entry.dayDate,
            'ext'          : Path(keogram_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : keogram_entry.camera.uuid,
            'camera_id'    : keogram_entry.camera.id,
        }


        if keogram_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_KEOGRAM_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_KEOGRAM_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : keogram_entry.__class__.__name__,
            'id'          : keogram_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_startrail(self, startrail_entry):
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL'):
            #logger.warning('Star trail uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : startrail_entry.dayDate,
            'ext'          : Path(startrail_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : startrail_entry.camera.uuid,
            'camera_id'    : startrail_entry.camera.id,
        }


        if startrail_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_STARTRAIL_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_STARTRAIL_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : startrail_entry.__class__.__name__,
            'id'          : startrail_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_startrail_video(self, startrail_video_entry):
        ### Upload video
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_STARTRAIL_VIDEO'):
            #logger.warning('Startrail video uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : startrail_video_entry.dayDate,
            'ext'          : Path(startrail_video_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : startrail_video_entry.camera.uuid,
            'camera_id'    : startrail_video_entry.camera.id,
        }


        if startrail_video_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_STARTRAIL_VIDEO_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_STARTRAIL_VIDEO_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : startrail_video_entry.__class__.__name__,
            'id'          : startrail_video_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_panorama(self, panorama_entry):
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_PANORAMA'):
            #logger.warning('Panorama uploading disabled')
            return


        panorama_remain = panorama_entry.id % int(self.config['FILETRANSFER']['UPLOAD_PANORAMA'])
        if panorama_remain != 0:
            next_image = int(self.config['FILETRANSFER']['UPLOAD_PANORAMA']) - panorama_remain
            logger.info('Next panorama upload in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
            return


        # Parameters for string formatting
        file_data_list = [
            self.config['IMAGE_FILE_TYPE'],
        ]


        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : panorama_entry.createDate,
            'ts'           : panorama_entry.createDate,  # shortcut
            'day_date'     : panorama_entry.dayDate,
            'ext'          : Path(panorama_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : panorama_entry.camera.uuid,
            'camera_id'    : panorama_entry.camera.id,
        }


        if panorama_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_PANORAMA_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_PANORAMA_NAME'].format(*file_data_list, **file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : panorama_entry.__class__.__name__,
            'id'          : panorama_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_raw_image(self, raw_image_entry):
        ### Upload RAW image
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_RAW'):
            #logger.warning('RAW image uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : raw_image_entry.dayDate,
            'ext'          : Path(raw_image_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : raw_image_entry.camera.uuid,
            'camera_id'    : raw_image_entry.camera.id,
        }


        if raw_image_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_RAW_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_RAW_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : raw_image_entry.__class__.__name__,
            'id'          : raw_image_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def upload_fits_image(self, fits_image_entry):
        ### Upload RAW image
        if not self.config.get('FILETRANSFER', {}).get('UPLOAD_FITS'):
            #logger.warning('FITS image uploading disabled')
            return


        now = datetime.now()

        # Parameters for string formatting
        file_data_dict = {
            'timestamp'    : now,
            'ts'           : now,  # shortcut
            'day_date'     : fits_image_entry.dayDate,
            'ext'          : Path(fits_image_entry.filename).suffix.replace('.', ''),
            'camera_uuid'  : fits_image_entry.camera.uuid,
            'camera_id'    : fits_image_entry.camera.id,
        }


        if fits_image_entry.night:
            file_data_dict['timeofday'] = 'night'
            file_data_dict['tod'] = 'night'  # shortcut
        else:
            file_data_dict['timeofday'] = 'day'
            file_data_dict['tod'] = 'day'  # shortcut


        # Replace parameters in names
        remote_dir = self.config['FILETRANSFER']['REMOTE_FITS_FOLDER'].format(**file_data_dict)
        remote_file = self.config['FILETRANSFER']['REMOTE_FITS_NAME'].format(**file_data_dict)

        remote_file_p = Path(remote_dir).joinpath(remote_file)


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_UPLOAD,
            'model'       : fits_image_entry.__class__.__name__,
            'id'          : fits_image_entry.id,
            'remote_file' : str(remote_file_p),
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def mqtt_publish_image(self, upload_filename, image_topic, mq_data):
        if not self.config.get('MQTTPUBLISH', {}).get('ENABLE'):
            #logger.warning('MQ publishing disabled')
            return

        # publish data to mq broker
        jobdata = {
            'action'      : constants.TRANSFER_MQTT,
            'local_file'  : str(upload_filename),
            'image_topic' : image_topic,
            'metadata'    : mq_data,
        }

        mqtt_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(mqtt_task)
        db.session.commit()

        self.upload_q.put({'task_id' : mqtt_task.id})


    def s3_upload_asset(self, asset_entry, asset_metadata):
        if not self.config.get('S3UPLOAD', {}).get('ENABLE'):
            #logger.warning('S3 uploading disabled')
            return

        if not asset_entry:
            #logger.warning('S3 uploading disabled')
            return

        logger.info('Uploading to S3 bucket')

        # publish data to s3 bucket
        jobdata = {
            'action'      : constants.TRANSFER_S3,
            'model'       : asset_entry.__class__.__name__,
            'id'          : asset_entry.id,
            'metadata'    : asset_metadata,
        }

        s3_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(s3_task)
        db.session.commit()

        self.upload_q.put({'task_id' : s3_task.id})


    def s3_upload_image(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_fits(self, *args):
        if not self.config.get('S3UPLOAD', {}).get('UPLOAD_FITS'):
            #logger.warning('S3 uploading disabled')
            return

        self.s3_upload_asset(*args)


    def s3_upload_raw(self, *args):
        if not self.config.get('S3UPLOAD', {}).get('UPLOAD_RAW'):
            #logger.warning('S3 uploading disabled')
            return

        self.s3_upload_asset(*args)


    def s3_upload_panorama(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_panorama_video(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_video(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_mini_video(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_keogram(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_startrail(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_startrail_video(self, *args):
        self.s3_upload_asset(*args)


    def s3_upload_thumbnail(self, *args):
        self.s3_upload_asset(*args)


    def syncapi_image(self, asset_entry, asset_metadata):
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return


        if not asset_entry:
            # image was not saved
            return


        # if s3 upload was previously completed, proceed with syncapi
        if not asset_entry.s3_key:
            if self.config.get('SYNCAPI', {}).get('POST_S3'):
                logger.warning('Delaying syncapi until after S3')
                # file is uploaded after s3 upload
                return


        if not asset_entry:
            # image was not saved
            return


        if not self.config.get('SYNCAPI', {}).get('UPLOAD_IMAGE'):
            #logger.warning('Image syncing disabled')
            return


        image_remain = asset_entry.id % int(self.config['SYNCAPI']['UPLOAD_IMAGE'])
        if image_remain != 0:
            next_image = int(self.config['SYNCAPI']['UPLOAD_IMAGE']) - image_remain
            logger.info('Next image sync in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
            return


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : asset_entry.__class__.__name__,
            'id'          : asset_entry.id,
            'metadata'    : asset_metadata,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def syncapi_video(self, asset_entry, metadata):
        ### sync camera
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return

        # if s3 upload was previously completed, proceed with syncapi
        if not asset_entry.s3_key:
            if self.config.get('SYNCAPI', {}).get('POST_S3'):
                logger.warning('Delaying syncapi until after S3')
                # file is uploaded after s3 upload
                return

        if not asset_entry:
            #logger.warning('S3 uploading disabled')
            return

        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : asset_entry.__class__.__name__,
            'id'          : asset_entry.id,
            'metadata'    : metadata,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def syncapi_mini_video(self, *args):
        self.syncapi_video(*args)


    def syncapi_keogram(self, *args):
        self.syncapi_video(*args)


    def syncapi_startrail(self, *args):
        self.syncapi_video(*args)


    def syncapi_startrail_video(self, *args):
        self.syncapi_video(*args)


    def syncapi_panorama_video(self, *args):
        self.syncapi_video(*args)


    def syncapi_thumbnail(self, *args):
        # this is for thumbnails of startrails and keograms mainly
        self.syncapi_video(*args)


    def syncapi_panorama(self, asset_entry, asset_metadata):
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return


        # if s3 upload was previously completed, proceed with syncapi
        if not asset_entry.s3_key:
            if self.config.get('SYNCAPI', {}).get('POST_S3'):
                logger.warning('Delaying syncapi until after S3')
                # file is uploaded after s3 upload
                return


        if not asset_entry:
            # image was not saved
            return


        if not self.config.get('SYNCAPI', {}).get('UPLOAD_PANORAMA'):
            #logger.warning('Image syncing disabled')
            return


        panorama_remain = asset_entry.id % int(self.config['SYNCAPI']['UPLOAD_PANORAMA'])
        if panorama_remain != 0:
            next_image = int(self.config['SYNCAPI']['UPLOAD_PANORAMA']) - panorama_remain
            logger.info('Next panorama sync in %d images (%d s)', next_image, int(self.config['EXPOSURE_PERIOD'] * next_image))
            return


        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : asset_entry.__class__.__name__,
            'id'          : asset_entry.id,
            'metadata'    : asset_metadata,
        }

        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def _youtube_upload(self, video_entry, metadata):
        if not self.config.get('YOUTUBE', {}).get('ENABLE'):
            return


        jobdata = {
            'action'      : constants.TRANSFER_YOUTUBE,
            'model'       : video_entry.__class__.__name__,
            'id'          : video_entry.id,
            'metadata'    : metadata,
        }


        upload_task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data=jobdata,
        )

        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})


    def youtube_upload_video(self, video_entry, metadata):
        if not self.config.get('YOUTUBE', {}).get('UPLOAD_VIDEO'):
            return

        metadata['asset_label'] = 'Timelapse'

        self._youtube_upload(video_entry, metadata)


    def youtube_upload_mini_video(self, video_entry, metadata):
        if not self.config.get('YOUTUBE', {}).get('UPLOAD_MINI_VIDEO'):
            return

        metadata['asset_label'] = 'Mini Timelapse'

        self._youtube_upload(video_entry, metadata)


    def youtube_upload_startrail_video(self, video_entry, metadata):
        if not self.config.get('YOUTUBE', {}).get('UPLOAD_STARTRAIL_VIDEO'):
            return

        metadata['asset_label'] = 'Star Trails Timelapse'

        self._youtube_upload(video_entry, metadata)


    def youtube_upload_panorama_video(self, video_entry, metadata):
        if not self.config.get('YOUTUBE', {}).get('UPLOAD_PANORAMA_VIDEO'):
            return

        metadata['asset_label'] = 'Panorama Timelapse'

        self._youtube_upload(video_entry, metadata)

