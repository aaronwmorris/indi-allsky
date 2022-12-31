from datetime import datetime
from datetime import timedelta
from pathlib import Path
import logging
#from pprint import pformat

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbBadPixelMapTable
from .models import IndiAllSkyDbDarkFrameTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbFitsImageTable
from .models import IndiAllSkyDbRawImageTable
from .models import IndiAllSkyDbNotificationTable

#from .models import NotificationCategory

from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger('indi_allsky')


class miscDb(object):
    def __init__(self, config):
        self.config = config


    def addCamera(self, camera_name):
        now = datetime.now()

        try:
            camera = IndiAllSkyDbCameraTable.query\
                .filter(IndiAllSkyDbCameraTable.name == camera_name)\
                .one()
            camera.connectDate = now
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=camera_name,
                connectDate=now,
            )

            db.session.add(camera)

        db.session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addImage(
        self,
        filename,
        camera_id,
        createDate,
        exposure,
        exp_elapsed,
        gain,
        binmode,
        temp,
        adu,
        stable,
        moonmode,
        moonphase,
        night=True,
        sqm=None,
        adu_roi=False,
        calibrated=False,
        stars=None,
        detections=0,
    ):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding image %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        # If temp is 0, write null
        if temp:
            temp_val = float(temp)
        else:
            temp_val = None


        # if moonmode is 0, moonphase is Null
        if moonmode:
            moonphase_val = float(moonphase)
        else:
            moonphase_val = None

        moonmode_val = bool(moonmode)

        night_val = bool(night)  # integer to boolean
        adu_roi_val = bool(adu_roi)


        if night:
            # day date for night is offset by 12 hours
            dayDate = (datetime.now() - timedelta(hours=12)).date()
        else:
            dayDate = datetime.now().date()


        image = IndiAllSkyDbImageTable(
            camera_id=camera_id,
            filename=filename_str,
            createDate=createDate,
            dayDate=dayDate,
            exposure=exposure,
            exp_elapsed=exp_elapsed,
            gain=gain,
            binmode=binmode,
            temp=temp_val,
            calibrated=calibrated,
            night=night_val,
            adu=adu,
            adu_roi=adu_roi_val,
            stable=stable,
            moonmode=moonmode_val,
            moonphase=moonphase_val,
            sqm=sqm,
            stars=stars,
            detections=detections,
        )

        db.session.add(image)
        db.session.commit()

        return image


    def addDarkFrame(self, filename, camera_id, bitdepth, exposure, gain, binmode, temp):
        if not filename:
            return

        #logger.info('####### Exposure: %s', pformat(exposure))

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding dark frame %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object

        exposure_int = int(exposure)


        # If temp is 0, write null
        if temp:
            temp_val = float(temp)
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        dark = IndiAllSkyDbDarkFrameTable(
            camera_id=camera_id,
            filename=filename_str,
            bitdepth=bitdepth,
            exposure=exposure_int,
            gain=gain,
            binmode=binmode,
            temp=temp_val,
        )

        db.session.add(dark)
        db.session.commit()

        return dark


    def addBadPixelMap(self, filename, camera_id, bitdepth, exposure, gain, binmode, temp):
        if not filename:
            return

        #logger.info('####### Exposure: %s', pformat(exposure))

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding bad pixel map %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object

        exposure_int = int(exposure)


        # If temp is 0, write null
        if temp:
            temp_val = float(temp)
        else:
            logger.warning('Temperature is not defined')
            temp_val = None


        bpm = IndiAllSkyDbBadPixelMapTable(
            camera_id=camera_id,
            filename=filename_str,
            bitdepth=bitdepth,
            exposure=exposure_int,
            gain=gain,
            binmode=binmode,
            temp=temp_val,
        )

        db.session.add(bpm)
        db.session.commit()

        return bpm


    def addVideo(self, filename, camera_id, dayDate, timeofday):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            # this is a normal condition, DB entry is created before file exists
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding video %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        video = IndiAllSkyDbVideoTable(
            camera_id=camera_id,
            filename=filename_str,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(video)
        db.session.commit()

        return video


    def addKeogram(self, filename, camera_id, dayDate, timeofday):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            # this is a normal condition, DB entry is created before file exists
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding keogram %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        keogram = IndiAllSkyDbKeogramTable(
            camera_id=camera_id,
            filename=filename_str,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(keogram)
        db.session.commit()

        return keogram


    def addStarTrail(self, filename, camera_id, dayDate, timeofday='night'):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            # this is a normal condition, DB entry is created before file exists
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding star trail %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        startrail = IndiAllSkyDbStarTrailsTable(
            camera_id=camera_id,
            filename=filename_str,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(startrail)
        db.session.commit()

        return startrail


    def addStarTrailVideo(self, filename, camera_id, dayDate, timeofday='night'):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            # this is a normal condition, DB entry is created before file exists
            logger.warning('File not found: %s', p_filename)


        logger.info('Adding star trail video %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        startrail_video = IndiAllSkyDbStarTrailsVideoTable(
            camera_id=camera_id,
            filename=filename_str,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(startrail_video)
        db.session.commit()

        return startrail_video


    def addFitsImage(self, filename, camera_id, createDate, exposure, gain, binmode, night=True):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.warning('File not found: %s', p_filename)


        if night:
            # day date for night is offset by 12 hours
            dayDate = (createDate - timedelta(hours=12)).date()
        else:
            dayDate = createDate.date()


        logger.info('Adding fits image %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        fits_image = IndiAllSkyDbFitsImageTable(
            camera_id=camera_id,
            filename=filename_str,
            createDate=createDate,
            exposure=exposure,
            gain=gain,
            binmode=binmode,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(fits_image)
        db.session.commit()

        return fits_image


    def addRawImage(self, filename, camera_id, createDate, exposure, gain, binmode, night=True):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.warning('File not found: %s', p_filename)


        if night:
            # day date for night is offset by 12 hours
            dayDate = (createDate - timedelta(hours=12)).date()
        else:
            dayDate = createDate.date()


        logger.info('Adding raw image %s to DB', filename)


        filename_str = str(filename)  # might be a pathlib object


        fits_image = IndiAllSkyDbRawImageTable(
            camera_id=camera_id,
            filename=filename_str,
            createDate=createDate,
            exposure=exposure,
            gain=gain,
            binmode=binmode,
            dayDate=dayDate,
            night=night,
        )

        db.session.add(fits_image)
        db.session.commit()

        return fits_image


    def addUploadedFlag(self, entry):
        entry.uploaded = True
        db.session.commit()


    def getCurrentCameraId(self):
        if self.config.get('DB_CCD_ID'):
            return self.config['DB_CCD_ID']
        else:
            try:
                camera = IndiAllSkyDbCameraTable.query\
                    .order_by(IndiAllSkyDbCameraTable.connectDate.desc())\
                    .limit(1)\
                    .one()
            except NoResultFound:
                logger.error('No cameras found')
                raise

        return camera.id


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
            expire=now + expire,
        )

        db.session.add(new_notice)
        db.session.commit()

        logger.info('Added %s notification: %d', category.value, new_notice.id)

        return new_notice


