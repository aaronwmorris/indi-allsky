from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.orm.exc import NoResultFound


import multiprocessing

logger = multiprocessing.get_logger()


Base = declarative_base()

#logging.getLogger('sqlalchemy').setLevel(logging.WARN)


class IndiAllSkyDb(object):
    def __init__(self):
        self._session = self._getDbConn()


    @property
    def session(self):
        return self._session

    @session.setter
    def session(self, foobar):
        pass  # readonly


    def _getDbConn(self):

        engine = create_engine('sqlite:////var/lib/indi-allsky/indi-allsky.sqlite', echo=False)
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

        return camera.id


    def addImage(self, camera_id, filename, exposure, gain, temp, adu, stable, moonmode, night=True, sqm=None, adu_roi=False):
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


        night_val = bool(night)  # integer to boolean
        adu_roi_val = bool(adu_roi)

        image = IndiAllSkyDbImageTable(
            camera_id=camera_id,
            filename=filename_str,
            exposure=exposure,
            gain=gain,
            temp=temp_val,
            night=night_val,
            adu=adu,
            adu_roi=adu_roi_val,
            stable=stable,
            moonmode=moonmode,
            moonphase=moonphase,
            sqm=sqm,
        )

        self._session.add(image)
        self._session.commit()

        return image



class IndiAllSkyDbVersionTable(Base):
    __tablename__ = 'version'

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)

    def __repr__(self):
        return '<Version {0:d}>'.format(self.id)


class IndiAllSkyDbCameraTable(Base):
    __tablename__ = 'camera'

    id = Column(Integer, primary_key=True)
    name = Column(String(length=100), unique=True, nullable=False)
    images = relationship('IndiAllSkyDbImageTable', back_populates='camera')
    videos = relationship('IndiAllSkyDbVideoTable', back_populates='camera')
    keograms = relationship('IndiAllSkyDbKeogramTable', back_populates='camera')


class IndiAllSkyDbImageTable(Base):
    __tablename__ = 'image'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    datetime = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    exposure = Column(Float, nullable=False)
    gain = Column(Integer, default=0, nullable=False)
    temp = Column(Float, nullable=True)
    night = Column(Boolean, default=True, nullable=False, index=True)
    adu = Column(Float, nullable=False)
    stable = Column(Boolean, default=True, nullable=False)
    moonmode = Column(Boolean, default=False, nullable=False)
    moonphase = Column(Float, nullable=True)
    adu_roi = Column(Boolean, default=False, nullable=False)
    sqm = Column(Float, nullable=True)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='images')

    def __repr__(self):
        return '<Image {0:s}>'.format(self.filename)


class IndiAllSkyDbVideoTable(Base):
    __tablename__ = 'video'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    datetime = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    night = Column(Boolean, default=True, nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='videos')

    def __repr__(self):
        return '<Video {0:s}>'.format(self.filename)


class IndiAllSkyDbKeogramTable(Base):
    __tablename__ = 'keogram'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    datetime = Column(DateTime(timezone=True), nullable=False, index=True, server_default=func.now())
    night = Column(Boolean, default=True, nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='keograms')

    def __repr__(self):
        return '<Keogram {0:s}>'.format(self.filename)

