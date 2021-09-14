from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship


import multiprocessing

logger = multiprocessing.get_logger()

#logging.getLogger('sqlalchemy').setLevel(logging.WARN)


Base = declarative_base()


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

