import datetime
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

from sqlalchemy.orm.exc import NoResultFound

logger = logging.getLogger('indi_allsky')


class miscDb(object):
    def __init__(self, config):
        self.config = config


    def addCamera(self, camera_name):
        now = datetime.datetime.now()

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


    def addImage(self, filename, camera_id, createDate, exposure, exp_elapsed, gain, binmode, temp, adu, stable, moonmode, moonphase, night=True, sqm=None, adu_roi=False, calibrated=False, stars=None):
        if not filename:
            return

        p_filename = Path(filename)
        if not p_filename.exists():
            logger.error('File not found: %s', p_filename)
            return

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
            dayDate = (datetime.datetime.now() - datetime.timedelta(hours=12)).date()
        else:
            dayDate = datetime.datetime.now().date()


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
            logger.error('File not found: %s', p_filename)
            return

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
            logger.error('File not found: %s', p_filename)
            return

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
            logger.error('File not found: %s', p_filename)
            return

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
            logger.error('File not found: %s', p_filename)
            return

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
            logger.error('File not found: %s', p_filename)
            return

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
                    .first()
            except NoResultFound:
                logger.error('No cameras found')
                raise

        return camera.id

