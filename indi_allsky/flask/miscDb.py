from datetime import datetime
from datetime import timedelta
from pathlib import Path
import uuid
import logging
#from pprint import pformat

import cv2
import PIL
from PIL import Image

from cryptography.fernet import Fernet

from flask import current_app as app  # prevent circular import
from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbBadPixelMapTable
from .models import IndiAllSkyDbDarkFrameTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbMiniVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbPanoramaImageTable
from .models import IndiAllSkyDbPanoramaVideoTable
from .models import IndiAllSkyDbThumbnailTable
from .models import IndiAllSkyDbLongTermKeogramTable
from .models import IndiAllSkyDbNotificationTable
from .models import IndiAllSkyDbStateTable

#from .models import NotificationCategory

from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound

from .. import constants
#from ..exceptions import BadImage

logger = logging.getLogger('indi_allsky')


class miscDb(object):
    def __init__(self, config):
        self.config = config


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()



    def addCamera(self, metadata):
        now = datetime.now()

        try:
            # not catching MultipleResultsFound
            camera = IndiAllSkyDbCameraTable.query\
                .filter(
                    or_(
                        IndiAllSkyDbCameraTable.name == metadata['name'],
                        IndiAllSkyDbCameraTable.name_alt1 == metadata['name'],
                        IndiAllSkyDbCameraTable.name_alt2 == metadata['name'],
                    )
                )\
                .one()
            camera.connectDate = now

            if not camera.uuid:
                camera.uuid = str(uuid.uuid4())
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=metadata['name'],
                connectDate=now,
                local=True,
                uuid=str(uuid.uuid4()),
            )

            db.session.add(camera)
            db.session.commit()


        keys_exclude = [
            'id',
            'name',
            'name_alt1',
            'name_alt2',
            'uuid',
            'type',
            'local',
            'filename',
            's3_key',
            'remote_url',
            'file_size',
            'data',  # manually handle data
            #'sync_id',
            #'friendlyName',
        ]

        # populate camera info
        for k, v in metadata.items():
            if k in keys_exclude:
                continue

            setattr(camera, k, v)


        if camera.data:
            camera_data = dict(camera.data)
        else:
            camera_data = dict()


        # update entries
        for k, v in metadata.get('data', {}).items():
            camera_data[k] = v

        camera.data = camera_data


        db.session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addCamera_remote(self, metadata):
        now = datetime.now()

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.uuid == metadata['uuid'])\
                .one()

            camera.connectDate = now
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=metadata['uuid'],  # use uuid initially for uniqueness
                connectDate=now,
                local=False,
                uuid=metadata['uuid'],
            )

            db.session.add(camera)
            db.session.commit()


        # The camera name and friendlyName must be unique
        camera.name = '{0:s} {1:d}'.format(metadata['name'], camera.id)

        if metadata.get('friendlyName'):
            camera.friendlyName = '{0:s} {1:d}'.format(metadata['friendlyName'], camera.id)


        keys_exclude = [
            'id',
            'name',
            'name_alt1',
            'name_alt2',
            'uuid',
            'type',
            'local',
            'sync_id',
            'friendlyName',
            'filename',
            's3_key',
            'remote_url',
            'hidden',
            'file_size',
            'web_nonlocal_images',
            'web_local_images_admin',
            'data',  # manually handle data
        ]

        # populate camera info
        for k, v in metadata.items():
            if k in keys_exclude:
                continue

            setattr(camera, k, v)


        if camera.data:
            camera_data = dict(camera.data)
        else:
            camera_data = dict()


        # update entries
        for k, v in metadata.get('data', {}).items():
            camera_data[k] = v

        camera.data = camera_data


        db.session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'exposure'
        #    'exp_elapsed'
        #    'gain'
        #    'binmode'
        #    'temp'
        #    'adu'
        #    'stable'
        #    'moonmode'
        #    'moonphase'
        #    'night'
        #    'sqm'
        #    'adu_roi'
        #    'calibrated'
        #    'stars'
        #    'detections'
        #    'process_elapsed'
        #    'data'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)  # file might not exist when entry created


        logger.info('Adding image %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']


        moonmode_val = bool(metadata['moonmode'])

        night_val = bool(metadata['night'])  # integer to boolean
        adu_roi_val = bool(metadata['adu_roi'])

        image = IndiAllSkyDbImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            createDate_year=createDate.year,
            createDate_month=createDate.month,
            createDate_day=createDate.day,
            createDate_hour=createDate.hour,
            dayDate=dayDate,
            exposure=metadata['exposure'],
            exp_elapsed=metadata['exp_elapsed'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=metadata['temp'],
            calibrated=metadata['calibrated'],
            night=night_val,
            adu=metadata['adu'],
            adu_roi=adu_roi_val,
            stable=metadata['stable'],
            moonmode=moonmode_val,
            moonphase=metadata['moonphase'],
            sqm=metadata['sqm'],
            stars=metadata['stars'],
            detections=metadata['detections'],
            process_elapsed=metadata['process_elapsed'],
            height=metadata['height'],
            width=metadata['width'],
            kpindex=metadata.get('kpindex'),
            ovation_max=metadata.get('ovation_max'),
            smoke_rating=metadata.get('smoke_rating'),
            exclude=metadata.get('exclude', False),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
            data=metadata.get('data', {}),
        )

        db.session.add(image)
        db.session.commit()

        return image


    def addDarkFrame(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'bitdepth'
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'temp'
        #    'adu'
        #    'width'
        #    'height'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding dark frame %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        exposure_int = int(metadata['exposure'])


        # If temp is 0, write null
        if metadata['temp']:
            temp_val = float(metadata['temp'])
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        dark = IndiAllSkyDbDarkFrameTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            bitdepth=metadata['bitdepth'],
            exposure=exposure_int,
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=temp_val,
            adu=metadata.get('adu'),
            height=metadata['height'],
            width=metadata['width'],
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
            data=metadata.get('data', {}),
        )

        db.session.add(dark)
        db.session.commit()

        return dark


    def addBadPixelMap(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'bitdepth'
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'temp'
        #    'adu'
        #    'width'
        #    'height'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding bad pixel map %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        exposure_int = int(metadata['exposure'])


        # If temp is 0, write null
        if metadata['temp']:
            temp_val = float(metadata['temp'])
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        bpm = IndiAllSkyDbBadPixelMapTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            bitdepth=metadata['bitdepth'],
            exposure=exposure_int,
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            temp=temp_val,
            adu=metadata.get('adu'),
            height=metadata['height'],
            width=metadata['width'],
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
            data=metadata.get('data', {}),
        )

        db.session.add(bpm)
        db.session.commit()

        return bpm


    def addVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'framerate'
        #    'frames'
        #    'data'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding video %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        video = IndiAllSkyDbVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            dayDate_year=dayDate.year,
            dayDate_month=dayDate.month,
            dayDate_day=dayDate.day,
            night=metadata['night'],
            framerate=float(metadata.get('framerate', 0.0)),
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(video)
        db.session.commit()

        return video


    def addMiniVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'targetDate'
        #    'startDate'
        #    'endDate'
        #    'framerate'
        #    'frames'
        #    'data'
        #    'note'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding video %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['targetDate'], (int, float)):
            targetDate = datetime.fromtimestamp(metadata['targetDate'])
        else:
            targetDate = metadata['targetDate']


        if isinstance(metadata['startDate'], (int, float)):
            startDate = datetime.fromtimestamp(metadata['startDate'])
        else:
            startDate = metadata['startDate']


        if isinstance(metadata['endDate'], (int, float)):
            endDate = datetime.fromtimestamp(metadata['endDate'])
        else:
            endDate = metadata['endDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']


        mini_video = IndiAllSkyDbMiniVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            dayDate_year=dayDate.year,
            dayDate_month=dayDate.month,
            dayDate_day=dayDate.day,
            night=metadata['night'],
            targetDate=targetDate,
            startDate=startDate,
            endDate=endDate,
            framerate=float(metadata.get('framerate', 0.0)),
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
            note=metadata['note']
        )

        db.session.add(mini_video)
        db.session.commit()

        return mini_video


    def addPanoramaVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'framerate'
        #    'frames'
        #    'data'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding video %s to DB', filename_p)

        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        panorama_video = IndiAllSkyDbPanoramaVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            night=metadata['night'],
            framerate=float(metadata.get('framerate', 0.0)),
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(panorama_video)
        db.session.commit()

        return panorama_video


    def addKeogram(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'frames'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding keogram %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        keogram = IndiAllSkyDbKeogramTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            night=metadata['night'],
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(keogram)
        db.session.commit()

        return keogram


    def addStarTrail(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'frames'
        #    'width'
        #    'height'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding star trail %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        startrail = IndiAllSkyDbStarTrailsTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            night=metadata['night'],
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(startrail)
        db.session.commit()

        return startrail


    def addStarTrailVideo(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'  # date or string
        #    'night'
        #    'framerate'
        #    'frames'
        #}


        if not filename:
            return

        filename_p = Path(filename)


        logger.info('Adding star trail video %s to DB', filename_p)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']



        startrail_video = IndiAllSkyDbStarTrailsVideoTable(
            createDate=createDate,
            camera_id=camera_id,
            filename=str(filename_p),
            success=metadata.get('success', False),  # original default was true
            dayDate=dayDate,
            night=metadata['night'],
            framerate=float(metadata.get('framerate', 0.0)),
            frames=metadata.get('frames', 0),
            height=metadata.get('height'),  # optional
            width=metadata.get('width'),  # optional
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(startrail_video)
        db.session.commit()

        return startrail_video


    def addFitsImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'     # date or string
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'night'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']


        logger.info('Adding fits image %s to DB', filename_p)


        fits_image = IndiAllSkyDbFitsImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            createDate_year=createDate.year,
            createDate_month=createDate.month,
            createDate_day=createDate.day,
            createDate_hour=createDate.hour,
            exposure=metadata['exposure'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            dayDate=dayDate,
            night=metadata['night'],
            height=metadata['height'],
            width=metadata['width'],
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(fits_image)
        db.session.commit()

        return fits_image


    def addRawImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'     # date or string
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'night'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']


        logger.info('Adding raw image %s to DB', filename_p)


        raw_image = IndiAllSkyDbRawImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            createDate_year=createDate.year,
            createDate_month=createDate.month,
            createDate_day=createDate.day,
            createDate_hour=createDate.hour,
            exposure=metadata['exposure'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            dayDate=dayDate,
            night=metadata['night'],
            height=metadata['height'],
            width=metadata['width'],
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(raw_image)
        db.session.commit()

        return raw_image


    def addPanoramaImage(self, filename, camera_id, metadata):

        ### expected metadata
        #{
        #    'createDate'  # datetime or timestamp
        #    'dayDate'     # date or string
        #    'exposure'
        #    'gain'
        #    'binmode'
        #    'night'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(metadata['createDate'])
        else:
            createDate = metadata['createDate']


        if isinstance(metadata['dayDate'], str):
            dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = metadata['dayDate']


        logger.info('Adding panorama image %s to DB', filename_p)


        panorama_image = IndiAllSkyDbPanoramaImageTable(
            camera_id=camera_id,
            filename=str(filename_p),
            createDate=createDate,
            createDate_year=createDate.year,
            createDate_month=createDate.month,
            createDate_day=createDate.day,
            createDate_hour=createDate.hour,
            exposure=metadata['exposure'],
            gain=metadata['gain'],
            binmode=metadata['binmode'],
            dayDate=dayDate,
            night=metadata['night'],
            height=metadata['height'],
            width=metadata['width'],
            data=metadata.get('data', {}),
            remote_url=metadata.get('remote_url'),
            s3_key=metadata.get('s3_key'),
            thumbnail_uuid=metadata.get('thumbnail_uuid'),
        )

        db.session.add(panorama_image)
        db.session.commit()

        return panorama_image


    def getCurrentCameraId(self):
        try:
            camera_id = int(self.getState('DB_CAMERA_ID'))
            return camera_id
        except NoResultFound:
            pass

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
                .limit(1)\
                .one()
            return camera.id
        except NoResultFound:
            logger.error('No cameras found')
            raise


    def addNotification(self, category, item, notification, expire=timedelta(hours=12)):
        now = datetime.now()

        # look for existing notification
        notice = IndiAllSkyDbNotificationTable.query\
            .filter(IndiAllSkyDbNotificationTable.item == item)\
            .filter(IndiAllSkyDbNotificationTable.category == category)\
            .filter(IndiAllSkyDbNotificationTable.expireDate > now)\
            .first()

        if notice:
            logger.warning('Not adding existing notification')
            return


        new_notice = IndiAllSkyDbNotificationTable(
            item=item,
            category=category,
            notification=notification,
            expireDate=now + expire,
        )

        db.session.add(new_notice)
        db.session.commit()

        logger.info('Added %s notification: %d', category.value, new_notice.id)

        return new_notice


    def setState(self, key, value, encrypted=False):
        now = datetime.now()

        # all keys must be upper-case
        key_upper = str(key).upper()

        # all values must be strings
        value_str = str(value)


        if encrypted:
            f_key = Fernet(app.config['PASSWORD_KEY'].encode())
            value_str = f_key.encrypt(value_str.encode()).decode()


        try:
            state = IndiAllSkyDbStateTable.query\
                .filter(IndiAllSkyDbStateTable.key == key_upper)\
                .one()

            state.value = value_str
            state.encrypted = encrypted
            state.createDate = now
        except NoResultFound:
            state = IndiAllSkyDbStateTable(
                key=key_upper,
                value=value_str,
                createDate=now,
                encrypted=encrypted,
            )

            db.session.add(state)


        db.session.commit()


    def setEncryptedState(self, key, value):
        self.setState(key, value, encrypted=True)


    def getState(self, key):
        # all values must be upper-case strings
        key_upper = str(key).upper()

        # not catching NoResultFound
        state = IndiAllSkyDbStateTable.query\
            .filter(IndiAllSkyDbStateTable.key == key_upper)\
            .one()


        if state.encrypted:
            f_key = Fernet(app.config['PASSWORD_KEY'].encode())
            value = f_key.decrypt(state.value.encode()).decode()
        else:
            value = state.value


        return value


    def removeState(self, key):
        # all values must be upper-case strings
        key_upper = str(key).upper()

        # not catching NoResultFound
        state = IndiAllSkyDbStateTable.query\
            .filter(IndiAllSkyDbStateTable.key == key_upper)\
            .one()


        db.session.delete(state)
        db.session.commit()


    def addThumbnail(self, entry, entry_metadata, camera_id, thumbnail_metadata, new_width=150, numpy_data=None, image_entry=None):
        if entry.thumbnail_uuid:
            return


        if isinstance(thumbnail_metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(thumbnail_metadata['createDate'])
        else:
            createDate = thumbnail_metadata['createDate']


        if isinstance(thumbnail_metadata['dayDate'], str):
            dayDate = datetime.strptime(thumbnail_metadata['dayDate'], '%Y%m%d').date()
        else:
            dayDate = thumbnail_metadata['dayDate']


        if thumbnail_metadata['night']:
            # day date for night is offset by 1 day
            timeofday = 'night'
        else:
            timeofday = 'day'


        thumbnail_uuid_str = str(uuid.uuid4())


        if thumbnail_metadata['origin'] in (
            constants.IMAGE,
            constants.PANORAMA_IMAGE,
        ):
            if thumbnail_metadata['origin'] == constants.PANORAMA_IMAGE:
                type_folder = 'panoramas'
            else:
                # constants.IMAGE
                type_folder = 'exposures'

            thumbnail_dir_p = self.image_dir.joinpath(
                'ccd_{0:s}'.format(thumbnail_metadata['camera_uuid']),
                type_folder,
                dayDate.strftime('%Y%m%d'),
                timeofday,
                createDate.strftime('%d_%H'),
                'thumbnails',
            )
        else:
            thumbnail_dir_p = self.image_dir.joinpath(
                'ccd_{0:s}'.format(thumbnail_metadata['camera_uuid']),
                'timelapse',
                dayDate.strftime('%Y%m%d'),
                'thumbnails',
            )


        thumbnail_filename_p = thumbnail_dir_p.joinpath(
            '{0:s}.jpg'.format(thumbnail_uuid_str),
        )

        logger.info('Adding thumbnail to DB: %s', thumbnail_filename_p)

        if not thumbnail_dir_p.exists():
            thumbnail_dir_p.mkdir(mode=0o755, parents=True)


        if not isinstance(numpy_data, type(None)):
            # process numpy data
            img = Image.fromarray(cv2.cvtColor(numpy_data, cv2.COLOR_BGR2RGB))

        elif image_entry:
            # use alternate image entry
            filename_p = Path(image_entry.getFilesystemPath())

            if not filename_p.exists():
                logger.error('Cannot create thumbnail: File not found: %s', filename_p)
                return

            try:
                img = Image.open(str(filename_p))
            except PIL.UnidentifiedImageError:
                logger.error('Cannot create thumbnail:  Bad Image')
                return

        else:
            # use entry file on filesystem
            filename_p = Path(entry.getFilesystemPath())

            if not filename_p.exists():
                logger.error('Cannot create thumbnail: File not found: %s', filename_p)
                return

            try:
                img = Image.open(str(filename_p))
            except PIL.UnidentifiedImageError:
                logger.error('Cannot create thumbnail:  Bad Image')
                return


        width, height = img.size

        if new_width < width:
            scale = new_width / width
            new_height = int(height * scale)

            thumbnail_data = img.resize((new_width, new_height))
        else:
            # keep the same dimensions
            thumbnail_data = img
            new_width = width
            new_height = height


        # insert new metadata
        entry_metadata['thumbnail_uuid'] = thumbnail_uuid_str
        thumbnail_metadata['uuid'] = thumbnail_uuid_str
        thumbnail_metadata['dayDate'] = dayDate.strftime('%Y%m%d')
        thumbnail_metadata['width'] = new_width
        thumbnail_metadata['height'] = new_height


        thumbnail_data.save(str(thumbnail_filename_p), quality=75)


        thumbnail_entry = IndiAllSkyDbThumbnailTable(
            uuid=thumbnail_uuid_str,
            filename=str(thumbnail_filename_p.relative_to(self.image_dir)),
            createDate=createDate,
            origin=thumbnail_metadata['origin'],
            width=new_width,
            height=new_height,
            camera_id=camera_id,
            data=thumbnail_metadata.get('data', {}),
            s3_key=thumbnail_metadata.get('s3_key'),
            remote_url=thumbnail_metadata.get('remote_url'),
        )

        db.session.add(thumbnail_entry)
        entry.thumbnail_uuid = thumbnail_uuid_str
        db.session.commit()

        return thumbnail_entry


    def addThumbnailImageAuto(self, *args, **kwargs):
        if not self.config.get('THUMBNAILS', {}).get('IMAGES_AUTO', True):
            return

        return self.addThumbnail(*args, **kwargs)


    def addThumbnail_remote(self, filename, camera_id, thumbnail_metadata):

        ### expected metadata
        #{
        #    'createDate'
        #    'uuid'
        #    'night'
        #    'width'
        #    'height'
        #}

        if not filename:
            return

        filename_p = Path(filename)


        if isinstance(thumbnail_metadata['createDate'], (int, float)):
            createDate = datetime.fromtimestamp(thumbnail_metadata['createDate'])
        else:
            createDate = thumbnail_metadata['createDate']


        logger.info('Adding thumbnail to DB: %s', filename_p)


        thumbnail_entry = IndiAllSkyDbThumbnailTable(
            uuid=thumbnail_metadata['uuid'],
            filename=str(filename_p),
            createDate=createDate,
            origin=thumbnail_metadata.get('origin', -1),  # remote might not send data
            width=thumbnail_metadata['width'],
            height=thumbnail_metadata['height'],
            camera_id=camera_id,
            data=thumbnail_metadata.get('data', {}),
            s3_key=thumbnail_metadata.get('s3_key'),
            remote_url=thumbnail_metadata.get('remote_url'),
        )

        db.session.add(thumbnail_entry)
        db.session.commit()

        return thumbnail_entry



    def add_long_term_keogram_data(self, exp_date, camera_id, rgb_pixel_list):

        if isinstance(exp_date, (int, float)):
            ts = exp_date
        else:
            # timestamps are UTC
            ts = exp_date.timestamp()


        # data is probably numpy types
        r1, g1, b1 = rgb_pixel_list[0]
        r2, g2, b2 = rgb_pixel_list[1]
        r3, g3, b3 = rgb_pixel_list[2]
        r4, g4, b4 = rgb_pixel_list[3]
        r5, g5, b5 = rgb_pixel_list[4]

        #logger.info('r1: %s, g1: %s, b1: %s', type(r1), type(g1), type(b1))
        #logger.info('r1: %d, g1: %d, b1: %d', r1, g1, b1)

        keogram_entry = IndiAllSkyDbLongTermKeogramTable(
            ts=int(ts),
            camera_id=camera_id,
            r1=int(r1),  # 1
            g1=int(g1),
            b1=int(b1),
            r2=int(r2),  # 2
            g2=int(g2),
            b2=int(b2),
            r3=int(r3),  # 3
            g3=int(g3),
            b3=int(b3),
            r4=int(r4),  # 4
            g4=int(g4),
            b4=int(b4),
            r5=int(r5),  # 5
            g5=int(g5),
            b5=int(b5),
        )
        db.session.add(keogram_entry)
        db.session.commit()

        return keogram_entry

