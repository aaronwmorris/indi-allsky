import enum
from pathlib import Path

from cryptography.fernet import Fernet
#from cryptography.fernet import InvalidToken

from sqlalchemy.sql import expression

from sqlalchemy.orm.exc import NoResultFound

from flask import current_app as app

from . import db


__all__ = (
    'IndiAllSkyDbCameraTable',
    'IndiAllSkyDbThumbnailTable',
    'IndiAllSkyDbImageTable',
    'IndiAllSkyDbBadPixelMapTable',
    'IndiAllSkyDbDarkFrameTable',
    'IndiAllSkyDbVideoTable',
    'IndiAllSkyDbMiniVideoTable',
    'IndiAllSkyDbKeogramTable',
    'IndiAllSkyDbStarTrailsTable',
    'IndiAllSkyDbStarTrailsVideoTable',
    'IndiAllSkyDbFitsImageTable',
    'IndiAllSkyDbRawImageTable',
    'IndiAllSkyDbPanoramaImageTable',
    'IndiAllSkyDbPanoramaVideoTable',
    'IndiAllSkyDbLongTermKeogramTable',
    'TaskQueueState', 'TaskQueueQueue', 'IndiAllSkyDbTaskQueueTable',
    'NotificationCategory', 'IndiAllSkyDbNotificationTable',
    'IndiAllSkyDbStateTable',
    'IndiAllSkyDbUserTable',
    'IndiAllSkyDbTleDataTable',
)


class IndiAllSkyDbCameraTable(db.Model):
    __tablename__ = 'camera'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(length=36), unique=True, index=True)
    name = db.Column(db.String(length=100), unique=True, nullable=False, index=True)
    name_alt1 = db.Column(db.String(length=100), nullable=True, index=True)
    name_alt2 = db.Column(db.String(length=100), nullable=True, index=True)
    driver = db.Column(db.String(length=100), nullable=True)
    friendlyName = db.Column(db.String(length=100), unique=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, server_default=db.func.now())
    connectDate = db.Column(db.DateTime(), nullable=True)
    hidden = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)

    minGain = db.Column(db.Integer, nullable=True)
    maxGain = db.Column(db.Integer, nullable=True)
    minExposure = db.Column(db.Float, nullable=True)
    maxExposure = db.Column(db.Float, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    bits = db.Column(db.Integer, nullable=True)
    pixelSize = db.Column(db.Float, nullable=True)
    cfa = db.Column(db.Integer(), nullable=True)  # maps to constants

    location = db.Column(db.String(length=100), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    elevation = db.Column(db.Integer, nullable=True)

    tz = db.Column(db.String(length=64), nullable=True)
    utc_offset = db.Column(db.Integer, server_default='0', nullable=False)

    alt = db.Column(db.Float, nullable=True)
    az = db.Column(db.Float, nullable=True)
    nightSunAlt = db.Column(db.Float, nullable=True)

    owner = db.Column(db.String(length=100), nullable=True)
    lensName = db.Column(db.String(length=100), nullable=True)
    lensFocalLength = db.Column(db.Float, nullable=True)
    lensFocalRatio = db.Column(db.Float, nullable=True)
    lensImageCircle = db.Column(db.Integer, nullable=True)  # pixels

    daytime_capture = db.Column(db.Boolean, server_default=expression.true(), nullable=False)
    daytime_capture_save = db.Column(db.Boolean, server_default=expression.true(), nullable=False)
    daytime_timelapse = db.Column(db.Boolean, server_default=expression.true(), nullable=False)
    capture_pause = db.Column(db.Boolean, server_default=expression.false(), nullable=False)

    s3_prefix = db.Column(db.String(length=255), nullable=True)
    web_nonlocal_images = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    web_local_images_admin = db.Column(db.Boolean, server_default=expression.false(), nullable=False)

    data = db.Column(db.JSON, index=True)

    local = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    sync_id = db.Column(db.Integer, nullable=True, index=True)

    thumbnails = db.relationship('IndiAllSkyDbThumbnailTable', back_populates='camera')
    images = db.relationship('IndiAllSkyDbImageTable', back_populates='camera')
    videos = db.relationship('IndiAllSkyDbVideoTable', back_populates='camera')
    minivideos = db.relationship('IndiAllSkyDbMiniVideoTable', back_populates='camera')
    keograms = db.relationship('IndiAllSkyDbKeogramTable', back_populates='camera')
    startrails = db.relationship('IndiAllSkyDbStarTrailsTable', back_populates='camera')
    startrailvideos = db.relationship('IndiAllSkyDbStarTrailsVideoTable', back_populates='camera')
    darkframes = db.relationship('IndiAllSkyDbDarkFrameTable', back_populates='camera')
    badpixelmaps = db.relationship('IndiAllSkyDbBadPixelMapTable', back_populates='camera')
    fitsimages = db.relationship('IndiAllSkyDbFitsImageTable', back_populates='camera')
    rawimages = db.relationship('IndiAllSkyDbRawImageTable', back_populates='camera')
    panoramaimages = db.relationship('IndiAllSkyDbPanoramaImageTable', back_populates='camera')
    panoramavideos = db.relationship('IndiAllSkyDbPanoramaVideoTable', back_populates='camera')
    longtermkeograms = db.relationship('IndiAllSkyDbLongTermKeogramTable', back_populates='camera')


    @property
    def filename(self):
        ### virtual property used for the sync api
        return 'camera'


    def validateFile(self):
        return True


    def deleteFile(self):
        pass


    def getFilesystemPath(self):
        ### virtual function used for the sync api
        return 'camera'


class IndiAllSkyDbFileBase(db.Model):
    __abstract__ = True


    def getRelativePath(self):
        filename_p = Path(self.filename)

        if not self.filename.startswith('/'):
            # filename is already relative
            return filename_p

        # this can raise ValueError
        rel_filename_p = filename_p.relative_to(app.config['INDI_ALLSKY_IMAGE_FOLDER'])

        return rel_filename_p


    def getUrl(self, s3_prefix='', local=True):
        if not local:
            if self.remote_url:
                return self.remote_url
            elif self.s3_key:
                return '{0:s}/{1:s}'.format(str(s3_prefix), self.s3_key)


        rel_filename_p = self.getRelativePath()

        return Path('images').joinpath(rel_filename_p)


    def getFilesystemPath(self):
        filename_p = Path(self.filename)

        if self.filename.startswith('/'):
            # filename is already fully qualified
            return filename_p

        full_filename_p = Path(app.config['INDI_ALLSKY_IMAGE_FOLDER']).joinpath(filename_p)

        return full_filename_p


    def validateFile(self):
        filename_p = self.getFilesystemPath()

        if filename_p.exists():
            return True

        return False


    def deleteFile(self):
        filename_p = self.getFilesystemPath()

        try:
            filename_p.unlink()
        except FileNotFoundError:
            pass
        # do not catch OSError here


    def deleteAsset(self):
        # use this path to delete all parts of entry
        if self.thumbnail_uuid:
            # delete thumbnail

            try:
                thumbnail_entry = IndiAllSkyDbThumbnailTable.query\
                    .filter(IndiAllSkyDbThumbnailTable.uuid == self.thumbnail_uuid)\
                    .one()

                thumbnail_entry.deleteAsset()

                db.session.delete(thumbnail_entry)
                db.session.commit()
            except NoResultFound:
                pass

        self.deleteFile()


class IndiAllSkyDbThumbnailTable(IndiAllSkyDbFileBase):
    __tablename__ = 'thumbnail'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(length=36), unique=True, index=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    origin = db.Column(db.Integer, nullable=True, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='thumbnails')

    def __repr__(self):
        return '<Thumbnail {0:s}>'.format(self.filename)


    @property
    def thumbnail_uuid(self):
        ### virtual property
        return None


    def deleteAsset(self):
        self.deleteFile()


class IndiAllSkyDbImageTable(IndiAllSkyDbFileBase):
    __tablename__ = 'image'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    createDate_year = db.Column(db.Integer, nullable=True, index=True)
    createDate_month = db.Column(db.Integer, nullable=True, index=True)
    createDate_day = db.Column(db.Integer, nullable=True, index=True)
    createDate_hour = db.Column(db.Integer, nullable=True, index=True)
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    exp_elapsed = db.Column(db.Float, nullable=True)
    process_elapsed = db.Column(db.Float, nullable=True)
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
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    calibrated = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    detections = db.Column(db.Integer, server_default='0', nullable=False, index=True)
    kpindex = db.Column(db.Float, nullable=True, index=True)
    ovation_max = db.Column(db.Integer, nullable=True, index=True)
    smoke_rating = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    #tags = db.Column(db.JSON, index=True)
    exclude = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='images')

    db.Index(
        'idx_image_createDate_iYmdHd_2',
        camera_id,
        createDate_year,
        createDate_month,
        createDate_day,
        createDate_hour,
        detections,
        remote_url,
        s3_key,
    )

    db.Index(
        'idx_image_createDate_ix',
        camera_id,
        createDate,
        exclude,
        remote_url,
        s3_key,
    )

    def __repr__(self):
        return '<Image {0:s}>'.format(self.filename)


class IndiAllSkyDbDarkFrameTable(IndiAllSkyDbFileBase):
    __tablename__ = 'darkframe'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    bitdepth = db.Column(db.Integer, nullable=False, index=True)
    exposure = db.Column(db.Integer, nullable=False, index=True)
    gain = db.Column(db.Integer, nullable=False, index=True)
    binmode = db.Column(db.Integer, server_default='1', nullable=False, index=True)
    temp = db.Column(db.Float, nullable=True, index=True)
    adu = db.Column(db.Float, nullable=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    active = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='darkframes')


    db.Index(
        'idx_darkframe_cbegbtwh_ix',
        camera_id,
        bitdepth,
        exposure,
        gain,
        binmode,
        temp,
        width,
        height,
        active,
    )


    def __repr__(self):
        return '<DarkFrame {0:s}>'.format(self.filename)


    @property
    def remote_url(self):
        # virtual property
        return None


    @property
    def s3_key(self):
        # virtual property
        return None


class IndiAllSkyDbBadPixelMapTable(IndiAllSkyDbFileBase):
    __tablename__ = 'badpixelmap'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    bitdepth = db.Column(db.Integer, nullable=False, index=True)
    exposure = db.Column(db.Integer, nullable=False, index=True)
    gain = db.Column(db.Integer, nullable=False, index=True)
    binmode = db.Column(db.Integer, server_default='1', nullable=False, index=True)
    temp = db.Column(db.Float, nullable=True, index=True)
    adu = db.Column(db.Float, nullable=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    active = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='badpixelmaps')


    db.Index(
        'idx_badpixelmap_cbegbtwh_ix',
        camera_id,
        bitdepth,
        exposure,
        gain,
        binmode,
        temp,
        width,
        height,
        active,
    )


    def __repr__(self):
        return '<BadPixelMap {0:s}>'.format(self.filename)


    @property
    def remote_url(self):
        # virtual property
        return None


    @property
    def s3_key(self):
        # virtual property
        return None


class IndiAllSkyDbVideoTable(IndiAllSkyDbFileBase):
    __tablename__ = 'video'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    dayDate_year = db.Column(db.Integer, nullable=True, index=True)
    dayDate_month = db.Column(db.Integer, nullable=True, index=True)
    dayDate_day = db.Column(db.Integer, nullable=True, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    framerate = db.Column(db.Float, server_default='0', nullable=False)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    #kpindex = db.Column(db.Float, nullable=True, index=True)
    #ovation_max = db.Column(db.Integer, nullable=True, index=True)
    #smoke_rating = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    #tags = db.Column(db.JSON, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    height = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='videos')

    db.Index(
        'idx_video_dayDate_Ym_2',
        dayDate_year,
        dayDate_month,
        night,
        remote_url,
        s3_key,
    )


    def __repr__(self):
        return '<Video {0:s}>'.format(self.filename)


class IndiAllSkyDbMiniVideoTable(IndiAllSkyDbFileBase):
    __tablename__ = 'minivideo'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    dayDate_year = db.Column(db.Integer, nullable=True, index=True)
    dayDate_month = db.Column(db.Integer, nullable=True, index=True)
    dayDate_day = db.Column(db.Integer, nullable=True, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    targetDate = db.Column(db.DateTime(), nullable=False, index=True)
    startDate = db.Column(db.DateTime(), nullable=False)
    endDate = db.Column(db.DateTime(), nullable=False)
    framerate = db.Column(db.Float, server_default='0', nullable=False)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    note = db.Column(db.String(length=255), nullable=False)
    data = db.Column(db.JSON, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    height = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='minivideos')

    db.Index(
        'idx_minivideo_dayDate_Ym_2',
        dayDate_year,
        dayDate_month,
        night,
        remote_url,
        s3_key,
    )


    def __repr__(self):
        return '<Mini Video {0:s}>'.format(self.filename)


class IndiAllSkyDbKeogramTable(IndiAllSkyDbFileBase):
    __tablename__ = 'keogram'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='keograms')

    def __repr__(self):
        return '<Keogram {0:s}>'.format(self.filename)


    db.Index(
        'idx_keogram_082824',
        dayDate,
        night,
        remote_url,
        s3_key,
        camera_id,
    )


class IndiAllSkyDbStarTrailsTable(IndiAllSkyDbFileBase):
    __tablename__ = 'startrail'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='startrails')

    def __repr__(self):
        return '<StarTrails {0:s}>'.format(self.filename)


    db.Index(
        'idx_startrails_082824',
        dayDate,
        night,
        remote_url,
        s3_key,
        camera_id,
    )


class IndiAllSkyDbStarTrailsVideoTable(IndiAllSkyDbFileBase):
    __tablename__ = 'startrailvideo'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    framerate = db.Column(db.Float, server_default='0', nullable=False)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    width = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    height = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='startrailvideos')

    def __repr__(self):
        return '<StarTrailVideo {0:s}>'.format(self.filename)


    db.Index(
        'idx_startrailsvideo_082824',
        dayDate,
        night,
        remote_url,
        s3_key,
        camera_id,
    )


class IndiAllSkyDbFitsImageTable(IndiAllSkyDbFileBase):
    __tablename__ = 'fitsimage'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    createDate_year = db.Column(db.Integer, nullable=True, index=True)
    createDate_month = db.Column(db.Integer, nullable=True, index=True)
    createDate_day = db.Column(db.Integer, nullable=True, index=True)
    createDate_hour = db.Column(db.Integer, nullable=True, index=True)
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='fitsimages')

    def __repr__(self):
        return '<FitsImage {0:s}>'.format(self.filename)


    db.Index(
        'idx_fitsimage_createDate_iYmdH_2',
        camera_id,
        createDate_year,
        createDate_month,
        createDate_day,
        createDate_hour,
        remote_url,
        s3_key,
    )


class IndiAllSkyDbRawImageTable(IndiAllSkyDbFileBase):
    __tablename__ = 'rawimage'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    createDate_year = db.Column(db.Integer, nullable=True, index=True)
    createDate_month = db.Column(db.Integer, nullable=True, index=True)
    createDate_day = db.Column(db.Integer, nullable=True, index=True)
    createDate_hour = db.Column(db.Integer, nullable=True, index=True)
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='rawimages')

    def __repr__(self):
        return '<RawImage {0:s}>'.format(self.filename)


    db.Index(
        'idx_rawimage_createDate_iYmdH_2',
        camera_id,
        createDate_year,
        createDate_month,
        createDate_day,
        createDate_hour,
        remote_url,
        s3_key,
    )


class IndiAllSkyDbPanoramaImageTable(IndiAllSkyDbFileBase):
    __tablename__ = 'panoramaimage'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    createDate_year = db.Column(db.Integer, nullable=True, index=True)
    createDate_month = db.Column(db.Integer, nullable=True, index=True)
    createDate_day = db.Column(db.Integer, nullable=True, index=True)
    createDate_hour = db.Column(db.Integer, nullable=True, index=True)
    dayDate = db.Column(db.Date, nullable=False, index=True)
    exposure = db.Column(db.Float, nullable=False)
    gain = db.Column(db.Integer, nullable=False)
    binmode = db.Column(db.Integer, server_default='1', nullable=False)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    exclude = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    width = db.Column(db.Integer, nullable=True, index=True)
    height = db.Column(db.Integer, nullable=True, index=True)
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='panoramaimages')

    def __repr__(self):
        return '<PanoramaImage {0:s}>'.format(self.filename)


    db.Index(
        'idx_panoramaimage_createDate_iYmdH_2',
        camera_id,
        createDate_year,
        createDate_month,
        createDate_day,
        createDate_hour,
        remote_url,
        s3_key,
    )


    db.Index(
        'idx_panoramaimage_createDate_ix',
        camera_id,
        createDate,
        exclude,
        remote_url,
        s3_key,
    )


class IndiAllSkyDbPanoramaVideoTable(IndiAllSkyDbFileBase):
    __tablename__ = 'panoramavideo'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    thumbnail_uuid = db.Column(db.String(length=36), nullable=True, index=True)
    remote_url = db.Column(db.String(length=255), nullable=True, index=True)
    s3_key = db.Column(db.String(length=255), nullable=True, index=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    sync_id = db.Column(db.Integer, nullable=True, index=True)
    success = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    framerate = db.Column(db.Float, server_default='0', nullable=False)
    frames = db.Column(db.Integer, server_default='0', nullable=False)
    width = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    height = db.Column(db.Integer, nullable=True, index=True)  # this may never be populated
    data = db.Column(db.JSON, index=True)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='panoramavideos')

    def __repr__(self):
        return '<PanoramaVideo {0:s}>'.format(self.filename)


    db.Index(
        'idx_panoramavideo_082824',
        dayDate,
        night,
        remote_url,
        s3_key,
        camera_id,
    )


class IndiAllSkyDbLongTermKeogramTable(db.Model):
    __tablename__ = 'longtermkeogram'

    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.Integer, nullable=False, index=True)
    r1 = db.Column(db.Integer, nullable=False)
    g1 = db.Column(db.Integer, nullable=False)
    b1 = db.Column(db.Integer, nullable=False)
    r2 = db.Column(db.Integer, nullable=False)
    g2 = db.Column(db.Integer, nullable=False)
    b2 = db.Column(db.Integer, nullable=False)
    r3 = db.Column(db.Integer, nullable=False)
    g3 = db.Column(db.Integer, nullable=False)
    b3 = db.Column(db.Integer, nullable=False)
    r4 = db.Column(db.Integer, nullable=False)
    g4 = db.Column(db.Integer, nullable=False)
    b4 = db.Column(db.Integer, nullable=False)
    r5 = db.Column(db.Integer, nullable=False)
    g5 = db.Column(db.Integer, nullable=False)
    b5 = db.Column(db.Integer, nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='longtermkeograms')


    db.Index(
        'idx_longterm_keogram_it_2',
        camera_id,
        ts,
    )


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
    MAIN    = 'main_q'


class IndiAllSkyDbTaskQueueTable(db.Model):
    __tablename__ = 'taskqueue'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    state = db.Column(db.Enum(TaskQueueState, length=20, native_enum=False), nullable=False, index=True)
    queue = db.Column(db.Enum(TaskQueueQueue, length=20, native_enum=False), nullable=False, index=True)
    priority = db.Column(db.Integer, nullable=True, index=True)  # lower value, higher priority (NULL is less than numbers for sqlite and mysql, higher for postgres)
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
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    expireDate = db.Column(db.DateTime(), nullable=False, index=True)
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


class IndiAllSkyDbConfigTable(db.Model):
    __tablename__ = 'config'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())  # this should be stored as UTC
    level = db.Column(db.String(length=12), nullable=False)
    encrypted = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    note = db.Column(db.String(length=255), nullable=False)
    data = db.Column(db.JSON, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # users can be deleted
    user = db.relationship('IndiAllSkyDbUserTable', back_populates='configs')


class IndiAllSkyDbStateTable(db.Model):
    __tablename__ = 'state'

    key = db.Column(db.String(length=32), primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, index=True, server_default=db.func.now())
    value = db.Column(db.String(length=4096), nullable=False)
    encrypted = db.Column(db.Boolean, server_default=expression.false(), nullable=False)


class IndiAllSkyDbUserTable(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, server_default=db.func.now())
    passwordDate = db.Column(db.DateTime(), nullable=False, server_default=db.func.now())
    apikeyDate = db.Column(db.DateTime(), nullable=True)
    loginDate = db.Column(db.DateTime(), nullable=True)
    loginIp = db.Column(db.String(255), nullable=True)  # X-Forwarded-For may contain multiple IPs
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255))
    apikey = db.Column(db.String(255))  # apikeys are encrypted
    active = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    staff = db.Column(db.Boolean, server_default=expression.true(), nullable=False, index=True)
    admin = db.Column(db.Boolean, server_default=expression.false(), nullable=False, index=True)
    data = db.Column(db.JSON, index=True)
    configs = db.relationship('IndiAllSkyDbConfigTable', back_populates='user')


    @property
    def is_active(self):
        return self.active


    @property
    def is_authenticated(self):
        return True


    @property
    def is_anonymous(self):
        return False


    @property
    def is_staff(self):
        return self.staff


    @property
    def is_admin(self):
        return self.admin


    def get_id(self):
        return self.id


    def getApiKey(self, password_key):
        f_key = Fernet(password_key.encode())
        return f_key.decrypt(self.apikey.encode()).decode()


    def setApiKey(self, apikey, password_key):
        f_key = Fernet(password_key.encode())
        self.apikey = f_key.encrypt(apikey.encode()).decode()
        db.session.commit()


class IndiAllSkyDbTleDataTable(db.Model):
    __tablename__ = 'tle_data'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(), nullable=False, server_default=db.func.now())
    title = db.Column(db.String(32), nullable=False, index=True)
    line1 = db.Column(db.String(80), nullable=False)
    line2 = db.Column(db.String(80), nullable=False)
    group = db.Column(db.Integer, nullable=True, index=True)
    ### these values would be camera dependent
    #next_rise = db.Column(db.DateTime(), nullable=True, index=True)
    #next_rise_az = db.Column(db.Float, nullable=True, index=True)
    #next_transit = db.Column(db.DateTime(), nullable=True, index=True)
    #next_set = db.Column(db.DateTime(), nullable=True, index=True)
    #next_set_az = db.Column(db.Float, nullable=True, index=True)
    #next_alt = db.Column(db.Float, nullable=True, index=True)

