import enum
from pathlib import Path

from sqlalchemy.sql import expression

from flask import current_app as app

from . import db


__all__ = (
    'IndiAllSkyDbCameraTable',
    'IndiAllSkyDbImageTable',
    'IndiAllSkyDbBadPixelMapTable',
    'IndiAllSkyDbDarkFrameTable',
    'IndiAllSkyDbVideoTable',
    'IndiAllSkyDbKeogramTable',
    'IndiAllSkyDbStarTrailsTable',
    'IndiAllSkyDbStarTrailsVideoTable',
    'IndiAllSkyDbFitsImageTable',
    'IndiAllSkyDbRawImageTable',
    'TaskQueueState', 'TaskQueueQueue', 'IndiAllSkyDbTaskQueueTable',
    'NotificationCategory', 'IndiAllSkyDbNotificationTable',
    'IndiAllSkyDbStateTable',
)


class IndiAllSkyDbCameraTable(db.Model):
    __tablename__ = 'camera'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(length=100), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, server_default=db.text("(datetime('now', 'localtime'))"))
    connectDate = db.Column(db.DateTime(timezone=False), nullable=True)
    minGain = db.Column(db.Integer, nullable=True)
    maxGain = db.Column(db.Integer, nullable=True)
    minExposure = db.Column(db.Float, nullable=True)
    maxExposure = db.Column(db.Float, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    bits = db.Column(db.Integer, nullable=True)
    pixelSize = db.Column(db.Float, nullable=True)
    images = db.relationship('IndiAllSkyDbImageTable', back_populates='camera')
    videos = db.relationship('IndiAllSkyDbVideoTable', back_populates='camera')
    keograms = db.relationship('IndiAllSkyDbKeogramTable', back_populates='camera')
    startrails = db.relationship('IndiAllSkyDbStarTrailsTable', back_populates='camera')
    startrailvideos = db.relationship('IndiAllSkyDbStarTrailsVideoTable', back_populates='camera')
    darkframes = db.relationship('IndiAllSkyDbDarkFrameTable', back_populates='camera')
    badpixelmaps = db.relationship('IndiAllSkyDbBadPixelMapTable', back_populates='camera')
    fitsimages = db.relationship('IndiAllSkyDbFitsImageTable', back_populates='camera')
    rawimages = db.relationship('IndiAllSkyDbRawImageTable', back_populates='camera')


class IndiAllSkyDbImageTable(db.Model):
    __tablename__ = 'image'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    exp_elapsed = db.Column(db.Float, nullable=True)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    temp = db.Column(db.Float, nullable=True)
    night = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    adu = db.Column(db.Float, nullable=False)
    stable = db.Column(db.Boolean, server_default=expression.true(), nullable=False)
    moonmode = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    moonphase = db.Column(db.Float, nullable=True)
    adu_roi = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sqm = db.Column(db.Float, nullable=True)
    stars = db.Column(db.Integer, nullable=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    calibrated = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    detections = db.Column(db.Integer, server_default='0', nullable=False, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='images')

    # SQLAlchemy tries to create this over and over
    #db.Index(
    #    'idx_image_createDate_YmdH',
    #    db.extract('year', createDate),
    #    db.extract('month', createDate),
    #    db.extract('day', createDate),
    #    db.extract('hour', createDate),
    #)


    def __repr__(self):
        return '<Image {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbDarkFrameTable(db.Model):
    __tablename__ = 'darkframe'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    bitdepth = db.Column(db.Integer, nullable=False, index=True)
    exposure = db.Column(db.Integer, nullable=False, index=True)
    gain = db.Column(db.Integer, nullable=False, index=True)
    binmode = db.Column(db.Integer, server_default='1', nullable=False, index=True)
    temp = db.Column(db.Float, nullable=True, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='darkframes')

    def __repr__(self):
        return '<DarkFrame {0:s}>'.format(self.filename)


class IndiAllSkyDbBadPixelMapTable(db.Model):
    __tablename__ = 'badpixelmap'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    bitdepth = db.Column(db.Integer, nullable=False, index=True)
    exposure = db.Column(db.Integer, nullable=False, index=True)
    gain = db.Column(db.Integer, nullable=False, index=True)
    binmode = db.Column(db.Integer, server_default='1', nullable=False, index=True)
    temp = db.Column(db.Float, nullable=True, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='badpixelmaps')

    def __repr__(self):
        return '<BadPixelMap {0:s}>'.format(self.filename)


class IndiAllSkyDbVideoTable(db.Model):
    __tablename__ = 'video'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    success = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='videos')

    # SQLAlchemy tries to create this over and over
    #db.Index(
    #    'idx_video_dayDate_Ym',
    #    db.extract('year', dayDate),
    #    db.extract('month', dayDate),
    #)


    def __repr__(self):
        return '<Video {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbKeogramTable(db.Model):
    __tablename__ = 'keogram'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    success = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='keograms')

    def __repr__(self):
        return '<Keogram {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbStarTrailsTable(db.Model):
    __tablename__ = 'startrail'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    success = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='startrails')

    def __repr__(self):
        return '<StarTrails {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbStarTrailsVideoTable(db.Model):
    __tablename__ = 'startrailvideo'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    success = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='startrailvideos')

    def __repr__(self):
        return '<StarTrailVideo {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbFitsImageTable(db.Model):
    __tablename__ = 'fitsimage'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='fitsimages')

    def __repr__(self):
        return '<FitsImage {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


class IndiAllSkyDbRawImageTable(db.Model):
    __tablename__ = 'rawimage'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='rawimages')

    def __repr__(self):
        return '<RawImage {0:s}>'.format(self.filename)


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUri(self):
        rel_filename_p = self.getRelativePath()
        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p




class TaskQueueState(enum.Enum):
    MANUAL  = 'Manual'
    QUEUED  = 'Queued'
    RUNNING = 'Running'
    SUCCESS = 'Success'
    FAILED  = 'Failed'
    EXPIRED = 'Expired'


class TaskQueueQueue(enum.Enum):
    IMAGE   = 'image_q'
    VIDEO   = 'video_q'
    UPLOAD  = 'upload_q'


class IndiAllSkyDbTaskQueueTable(db.Model):
    __tablename__ = 'taskqueue'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    state = db.Column(db.Enum(TaskQueueState, length=20, native_enum=False), nullable=False, index=True)
    queue = db.Column(db.Enum(TaskQueueQueue, length=20, native_enum=False), nullable=False, index=True)
    data = db.Column(db.JSON)
    result = db.Column(db.String(length=255), nullable=True)


    def setQueued(self):
        self.state = TaskQueueState.QUEUED
        db.session.commit()

    def setRunning(self):
        self.state = TaskQueueState.RUNNING
        db.session.commit()

    def setSuccess(self, result):
        self.state = TaskQueueState.SUCCESS
        self.result = result
        db.session.commit()

    def setFailed(self, result):
        self.state = TaskQueueState.FAILED
        self.result = result
        db.session.commit()

    def setExpired(self):
        self.state = TaskQueueState.EXPIRED
        db.session.commit()



class NotificationCategory(enum.Enum):
    GENERAL    = 'General'
    MISC       = 'Miscellaneous'
    CAMERA     = 'Camera'
    WORKER     = 'Worker'
    MEDIA      = 'Media'    # image and video related
    DISK       = 'Disk'
    UPLOAD     = 'Upload'   # file transfer related
    STATE      = 'State'


class IndiAllSkyDbNotificationTable(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    expireDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime', '+12 hours'))"))
    ack = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    category = db.Column(db.Enum(NotificationCategory, length=20, native_enum=False), nullable=False, index=True)
    item = db.Column(db.String(length=32), nullable=False, index=True)
    notification = db.Column(db.String(length=255), nullable=False)


    def setAck(self):
        self.ack = True
        db.session.commit()


    def setExpired(self):
        self.expired = True
        db.session.commit()


class IndiAllSkyDbStateTable(db.Model):
    __tablename__ = 'state'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    key = db.Column(db.String(length=32), unique=True, nullable=False, index=True)
    value = db.Column(db.String(length=255), nullable=False)

