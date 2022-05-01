from pathlib import Path

from sqlalchemy.sql import expression

from flask import current_app as app

from . import db


class IndiAllSkyDbCameraTable(db.Model):
    __tablename__ = 'camera'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(length=100), unique=True, nullable=False)
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, server_default=db.text("(datetime('now', 'localtime'))"))
    #connectDate = db.Column(db.DateTime(timezone=True), nullable=True)
    connectDate = db.Column(db.DateTime(timezone=False), nullable=True)
    images = db.relationship('IndiAllSkyDbImageTable', back_populates='camera')
    videos = db.relationship('IndiAllSkyDbVideoTable', back_populates='camera')
    keograms = db.relationship('IndiAllSkyDbKeogramTable', back_populates='camera')
    startrails = db.relationship('IndiAllSkyDbStarTrailsTable', back_populates='camera')
    darkframes = db.relationship('IndiAllSkyDbDarkFrameTable', back_populates='camera')


class IndiAllSkyDbImageTable(db.Model):
    __tablename__ = 'image'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, index=True, server_default=db.func.now())
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
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, index=True, server_default=db.func.now())
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


class IndiAllSkyDbVideoTable(db.Model):
    __tablename__ = 'video'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(length=255), unique=True, nullable=False)
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, index=True, server_default=db.func.now())
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera.id'), nullable=False)
    camera = db.relationship('IndiAllSkyDbCameraTable', back_populates='videos')

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
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, index=True, server_default=db.func.now())
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
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
    #createDate = db.Column(db.DateTime(timezone=True), nullable=False, index=True, server_default=db.func.now())
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    dayDate = db.Column(db.Date, nullable=False, index=True)
    night = db.Column(db.Boolean, default=expression.true(), nullable=False, index=True)
    uploaded = db.Column(db.Boolean, server_default=expression.false(), nullable=False)
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



class IndiAllSkyDbTaskQueueTable(db.Model):
    __tablename__ = 'task'

    id = db.Column(db.Integer, primary_key=True)
    createDate = db.Column(db.DateTime(timezone=False), nullable=False, index=True, server_default=db.text("(datetime('now', 'localtime'))"))
    state = db.Column(db.String(length=30), nullable=False, index=True, server_default=db.text("init"))
    jobtype = db.Column(db.String(length=30), nullable=False, index=True)
    jobdata = db.Column(db.JSON)


    ### states
    # init
    # queued
    # running
    # success
    # failed


    def setQueued(self, session):
        self.state = 'queued'
        session.commit()

    def setRunning(self, session):
        self.state = 'running'
        session.commit()

    def setSuccess(self, session):
        self.state = 'success'
        session.commit()

    def setFailed(self, session):
        self.state = 'failed'
        session.commit()


