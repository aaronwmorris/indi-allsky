import datetime

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import Base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound

import multiprocessing

logger = multiprocessing.get_logger()


DATABASE_URI = 'sqlite:////var/lib/indi-allsky/indi-allsky.sqlite'


class IndiAllSkyDb(object):
    def __init__(self, config):
        self.config = config

        self._session = self._getDbConn()


    @property
    def session(self):
        return self._session

    @session.setter
    def session(self, foobar):
        pass  # readonly


    def _getDbConn(self):

        engine = create_engine(DATABASE_URI, echo=False)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        return Session()



    def addCamera(self, camera_name):
        try:
            camera = self._session.query(IndiAllSkyDbCameraTable).filter(IndiAllSkyDbCameraTable.name == camera_name).one()
        except NoResultFound:
            camera = IndiAllSkyDbCameraTable(
                name=camera_name,
            )

            self._session.add(camera)
            self._session.commit()

        logger.info('Camera DB ID: %d', camera.id)

        return camera


    def addImage(self, filename, exposure, gain, temp, adu, stable, moonmode, night=True, sqm=None, adu_roi=False):
        if not filename:
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
            moonphase = float(moonmode)
        else:
            moonphase = None

        moonmode_val = bool(moonmode)

        night_val = bool(night)  # integer to boolean
        adu_roi_val = bool(adu_roi)


        if night:
            # day date for night is offset by 12 hours
            daydate = datetime.datetime.now() - datetime.timedelta(hours=12)
        else:
            daydate = datetime.datetime.now()


        image = IndiAllSkyDbImageTable(
            camera_id=self.config['DB_CCD_ID'],
            filename=filename_str,
            daydate=daydate,
            exposure=exposure,
            gain=gain,
            temp=temp_val,
            night=night_val,
            adu=adu,
            adu_roi=adu_roi_val,
            stable=stable,
            moonmode=moonmode_val,
            moonphase=moonphase,
            sqm=sqm,
        )

        self._session.add(image)
        self._session.commit()

        return image


    def addVideo(self, filename, timeofday):
        if not filename:
            return

        logger.info('Adding video %s to DB', filename)

        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        if night:
            # day date for night is offset by 12 hours
            daydate = datetime.datetime.now() - datetime.timedelta(hours=12)
        else:
            daydate = datetime.datetime.now()


        video = IndiAllSkyDbVideoTable(
            camera_id=self.config['DB_CCD_ID'],
            filename=filename_str,
            daydate=daydate,
            night=night,
        )

        self._session.add(video)
        self._session.commit()

        return video


    def addKeogram(self, filename, timeofday):
        if not filename:
            return

        logger.info('Adding keogram %s to DB', filename)

        filename_str = str(filename)  # might be a pathlib object


        if timeofday == 'night':
            night = True
        else:
            night = False


        if night:
            # day date for night is offset by 12 hours
            daydate = datetime.datetime.now() - datetime.timedelta(hours=12)
        else:
            daydate = datetime.datetime.now()


        keogram = IndiAllSkyDbKeogramTable(
            camera_id=self.config['DB_CCD_ID'],
            filename=filename_str,
            daydate=daydate,
            night=night,
        )

        self._session.add(keogram)
        self._session.commit()

        return keogram



