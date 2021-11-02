from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Date
from sqlalchemy import func
from sqlalchemy import ForeignKey
from sqlalchemy.sql import expression
from sqlalchemy.orm import relationship


import multiprocessing

logger = multiprocessing.get_logger()

#logging.getLogger('sqlalchemy').setLevel(logging.WARN)


Base = declarative_base()


class IndiAllSkyDbCameraTable(Base):
    __tablename__ = 'camera'

    id = Column(Integer, primary_key=True)
    name = Column(String(length=100), unique=True, nullable=False)
    createDate = Column(DateTime, nullable=False, server_default=func.now())
    images = relationship('IndiAllSkyDbImageTable', back_populates='camera')
    videos = relationship('IndiAllSkyDbVideoTable', back_populates='camera')
    keograms = relationship('IndiAllSkyDbKeogramTable', back_populates='camera')
    darkframes = relationship('IndiAllSkyDbDarkFrameTable', back_populates='camera')


class IndiAllSkyDbImageTable(Base):
    __tablename__ = 'image'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    createDate = Column(DateTime, nullable=False, index=True, server_default=func.now())
    dayDate = Column(Date, nullable=False, index=True)
    exposure = Column(Float, nullable=False)
    gain = Column(Integer, nullable=False)
    binmode = Column(Integer, server_default='1', nullable=False)
    temp = Column(Float, nullable=True)
    night = Column(Boolean, server_default=expression.true(), nullable=False, index=True)
    adu = Column(Float, nullable=False)
    stable = Column(Boolean, server_default=expression.true(), nullable=False)
    moonmode = Column(Boolean, server_default=expression.false(), nullable=False)
    moonphase = Column(Float, nullable=True)
    adu_roi = Column(Boolean, server_default=expression.false(), nullable=False)
    sqm = Column(Float, nullable=True)
    stars = Column(Integer, nullable=True)
    uploaded = Column(Boolean, server_default=expression.false(), nullable=False)
    calibrated = Column(Boolean, server_default=expression.false(), nullable=False)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='images')

    def __repr__(self):
        return '<Image {0:s}>'.format(self.filename)


class IndiAllSkyDbDarkFrameTable(Base):
    __tablename__ = 'darkframe'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    createDate = Column(DateTime, nullable=False, index=True, server_default=func.now())
    bitdepth = Column(Integer, nullable=False, index=True)
    exposure = Column(Integer, nullable=False, index=True)
    gain = Column(Integer, nullable=False, index=True)
    binmode = Column(Integer, server_default='1', nullable=False, index=True)
    temp = Column(Float, nullable=True, index=True)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='darkframes')

    def __repr__(self):
        return '<DarkFrame {0:s}>'.format(self.filename)


class IndiAllSkyDbVideoTable(Base):
    __tablename__ = 'video'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    createDate = Column(DateTime, nullable=False, index=True, server_default=func.now())
    dayDate = Column(Date, nullable=False, index=True)
    night = Column(Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = Column(Boolean, server_default=expression.false(), nullable=False)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='videos')

    def __repr__(self):
        return '<Video {0:s}>'.format(self.filename)


class IndiAllSkyDbKeogramTable(Base):
    __tablename__ = 'keogram'

    id = Column(Integer, primary_key=True)
    filename = Column(String(length=255), unique=True, nullable=False)
    createDate = Column(DateTime, nullable=False, index=True, server_default=func.now())
    dayDate = Column(Date, nullable=False, index=True)
    night = Column(Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = Column(Boolean, server_default=expression.false(), nullable=False)
    camera_id = Column(Integer, ForeignKey('camera.id'), nullable=False)
    camera = relationship('IndiAllSkyDbCameraTable', back_populates='keograms')

    def __repr__(self):
        return '<Keogram {0:s}>'.format(self.filename)

