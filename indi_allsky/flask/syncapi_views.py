#import os
#import io
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import hashlib
import json
import tempfile
import shutil


from flask import request
from flask import Blueprint
from flask import jsonify
from flask import abort
from flask import current_app as app

#from flask_login import login_required

#from .. import constants

from .base_views import BaseView

from . import db

from .models import IndiAllSkyDbCameraTable
from .models import IndiAllSkyDbImageTable
from .models import IndiAllSkyDbVideoTable
from .models import IndiAllSkyDbKeogramTable
from .models import IndiAllSkyDbStarTrailsTable
from .models import IndiAllSkyDbStarTrailsVideoTable
from .models import IndiAllSkyDbUserTable

from sqlalchemy.orm.exc import NoResultFound


bp_syncapi_allsky = Blueprint(
    'syncapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class SyncApiBaseView(BaseView):
    decorators = []


    def __init__(self, **kwargs):
        super(SyncApiBaseView, self).__init__(**kwargs)

        if self.indi_allsky_config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.parent.joinpath('html', 'images').absolute()


    def dispatch_request(self):
        self.authorize()

        # we are now authenticated

        if request.method == 'POST':
            return self.post()
        elif request.method == 'PUT':
            return self.put()
        else:
            return jsonify({}), 400


    def post(self):
        metadata = self.saveMetadata()
        media_file = self.saveFile()

        camera = self.getCamera(metadata['camera_uuid'])


        try:
            file_entry = self.processFile(camera, metadata, media_file)
        except FileExists:
            return jsonify({'error' : 'file_exists'}), 400


        return jsonify({'id' : file_entry.id})


    def put(self):
        metadata = self.saveMetadata()
        media_file = self.saveFile()

        camera = self.getCamera(metadata['camera_uuid'])


        file_entry = self.processFile(camera, metadata, media_file, overwrite=True)


        return jsonify({'id' : file_entry.id})



    def processFile(self, **kwargs):
        # override in class
        pass


    def saveMetadata(self):
        metadata_file = request.files['metadata']
        metadata_json = json.load(metadata_file)

        #app.logger.info('Json: %s', metadata_json)

        return metadata_json


    def saveFile(self):
        media_file = request.files['media']

        media_file_p = Path(media_file.filename)  # need this for the extension

        f_tmp_media = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=media_file_p.suffix)
        while True:
            data = media_file.read(32768)
            if data:
                f_tmp_media.write(data)
            else:
                break

        f_tmp_media.close()

        #app.logger.info('File: %s', media_file_p)

        return Path(f_tmp_media.name)



    #def put(self):
    #    #media_file = request.files.get('media')
    #    pass


    def authorize(self):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            app.logger.error('Missing Authoriation header')
            return abort(400)

        try:
            bearer, user_apikey_hash = auth_header.split(' ')
        except ValueError:
            app.logger.error('Malformed API key')
            return abort(400)


        try:
            username, apikey_hash = user_apikey_hash.split(':')
        except ValueError:
            app.logger.error('Malformed API key')
            return abort(400)


        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not user:
            app.logger.error('Unknown user')
            return abort(400)


        time_floor = int(time.time() / 300) * 300


        apikey = user.getApiKey(app.config['PASSWORD_KEY'])

        hash1 = hashlib.sha256('{0:d}{1:s}'.format(time_floor, apikey).encode()).hexdigest()
        if apikey_hash != hash1:
            # we do not need to calculate the 2nd hash if the first one works
            hash2 = hashlib.sha256('{0:d}{1:s}'.format(time_floor + 1, apikey).encode()).hexdigest()
            if apikey_hash != hash2:
                app.logger.error('Unable to authenticate API key')
                return abort(400)


    def getCamera(self, camera_uuid):
        # not catching NoResultFound
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.uuid == camera_uuid)\
            .one()

        return camera


    def getDateFolder(self, exp_date, night):
        if night:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
        else:
            # daytime
            # images should be written to current day's folder
            day_ref = exp_date

        date_folder = self.image_dir.joinpath(day_ref.strftime('%Y%m%d'))

        return date_folder


    def getImageFolder(self, exp_date, night):
        date_folder = self.getDateFolder(exp_date, night)

        if night:
            timeofday_str = 'night'
        else:
            # daytime
            # images should be written to current day's folder
            timeofday_str = 'day'

        hour_str = exp_date.strftime('%d_%H')

        day_folder = date_folder.joinpath(timeofday_str)

        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder


class SyncApiImageView(SyncApiBaseView):
    decorators = []

    image_filename_t = 'ccd{0:d}_{1:s}{2:s}'  # no dot for extension


    def processFile(self, camera, image_metadata, tmp_file, overwrite=False):
        createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(createDate, image_metadata['night'])

        date_str = createDate.strftime('%Y%m%d_%H%M%S')
        image_file = folder.joinpath(self.image_filename_t.format(camera.id, date_str, tmp_file.suffix))  # suffix includes dot


        if not image_file.exists():
            try:
                # delete old entry if it exists
                old_image_entry = IndiAllSkyDbImageTable.query\
                    .filter(IndiAllSkyDbImageTable.filename == str(image_file))\
                    .one()

                app.logger.warning('Removing orphaned image entry')
                db.session.delete(old_image_entry)
                db.session.commit()
            except NoResultFound:
                pass


        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing image')
            image_file.unlink()

            try:
                old_image_entry = IndiAllSkyDbImageTable.query\
                    .filter(IndiAllSkyDbImageTable.filename == str(image_file))\
                    .one()

                app.logger.warning('Removing old image entry')
                db.session.delete(old_image_entry)
                db.session.commit()
            except NoResultFound:
                pass


        image_entry = self._miscDb.addImage(
            image_file,
            camera.id,
            image_metadata,
        )

        shutil.move(str(tmp_file), str(image_file))
        image_file.chmod(0o644)


        app.logger.info('Uploaded image: %s', image_file)

        return image_entry


class SyncApiVideoView(SyncApiBaseView):
    decorators = []


    def processFile(self, camera, video_metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(video_metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)

        video_file = date_folder.joinpath('allsky-timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), video_metadata['timeofday'], tmp_file.suffix))

        if not video_file.exists():
            try:
                # delete old entry if it exists
                old_video_entry = IndiAllSkyDbVideoTable.query\
                    .filter(IndiAllSkyDbVideoTable.filename == str(video_file))\
                    .one()

                app.logger.warning('Removing orphaned video entry')
                db.session.delete(old_video_entry)
                db.session.commit()
            except NoResultFound:
                pass

        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing video')
            video_file.unlink()

            try:
                old_video_entry = IndiAllSkyDbVideoTable.query\
                    .filter(IndiAllSkyDbVideoTable.filename == str(video_file))\
                    .one()

                app.logger.warning('Removing old video entry')
                db.session.delete(old_video_entry)
                db.session.commit()
            except NoResultFound:
                pass


        video_entry = self._miscDb.addVideo(
            video_file,
            camera.id,
            video_metadata,
        )

        shutil.move(str(tmp_file), str(video_file))
        video_file.chmod(0o644)

        app.logger.info('Uploaded video: %s', video_file)

        return video_entry


class SyncApiKeogramView(SyncApiBaseView):
    decorators = []


    def processFile(self, camera, keogram_metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(keogram_metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)


        keogram_file = date_folder.joinpath('allsky-keogram_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), keogram_metadata['timeofday'], tmp_file.suffix))


        if not keogram_file.exists():
            try:
                # delete old entry if it exists
                old_keogram_entry = IndiAllSkyDbKeogramTable.query\
                    .filter(IndiAllSkyDbKeogramTable.filename == str(keogram_file))\
                    .one()

                app.logger.warning('Removing orphaned keogram entry')
                db.session.delete(old_keogram_entry)
                db.session.commit()
            except NoResultFound:
                pass


        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing keogram')
            keogram_file.unlink()

            try:
                old_keogram_entry = IndiAllSkyDbKeogramTable.query\
                    .filter(IndiAllSkyDbKeogramTable.filename == str(keogram_file))\
                    .one()

                app.logger.warning('Removing old keogram entry')
                db.session.delete(old_keogram_entry)
                db.session.commit()
            except NoResultFound:
                pass


        keogram_entry = self._miscDb.addKeogram(
            keogram_file,
            camera.id,
            keogram_metadata,
        )

        shutil.move(str(tmp_file), str(keogram_file))
        keogram_file.chmod(0o644)


        app.logger.info('Uploaded keogram: %s', keogram_file)

        return keogram_entry


class SyncApiStartrailView(SyncApiBaseView):
    decorators = []


    def processFile(self, camera, startrail_metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(startrail_metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)


        startrail_file = date_folder.joinpath('allsky-startrail_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), startrail_metadata['timeofday'], tmp_file.suffix))


        if not startrail_file.exists():
            try:
                # delete old entry if it exists
                old_startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                    .filter(IndiAllSkyDbStarTrailsTable.filename == str(startrail_file))\
                    .one()

                app.logger.warning('Removing orphaned startrail entry')
                db.session.delete(old_startrail_entry)
                db.session.commit()
            except NoResultFound:
                pass

        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing star trail')
            startrail_file.unlink()

            try:
                old_startrail_entry = IndiAllSkyDbStarTrailsTable.query\
                    .filter(IndiAllSkyDbStarTrailsTable.filename == str(startrail_file))\
                    .one()

                app.logger.warning('Removing old startrail entry')
                db.session.delete(old_startrail_entry)
                db.session.commit()
            except NoResultFound:
                pass


        startrail_entry = self._miscDb.addStarTrail(
            startrail_file,
            camera.id,
            startrail_metadata,
        )


        shutil.move(str(tmp_file), str(startrail_file))
        startrail_file.chmod(0o644)


        app.logger.info('Uploaded startrail: %s', startrail_file)

        return startrail_entry


class SyncApiStartrailVideoView(SyncApiBaseView):
    decorators = []


    def processFile(self, camera, startrail_video_metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(startrail_video_metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)


        startrail_video_file = date_folder.joinpath('allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), startrail_video_metadata['timeofday'], tmp_file.suffix))


        if not startrail_video_file.exists():
            try:
                # delete old entry if it exists
                old_startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                    .filter(IndiAllSkyDbStarTrailsVideoTable.filename == str(startrail_video_file))\
                    .one()

                app.logger.warning('Removing orphaned startrail video entry')
                db.session.delete(old_startrail_video_entry)
                db.session.commit()
            except NoResultFound:
                pass


        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing Star trail video')
            startrail_video_file.unlink()

            try:
                old_startrail_video_entry = IndiAllSkyDbStarTrailsVideoTable.query\
                    .filter(IndiAllSkyDbStarTrailsVideoTable.filename == str(startrail_video_file))\
                    .one()

                app.logger.warning('Removing old startrail video entry')
                db.session.delete(old_startrail_video_entry)
                db.session.commit()
            except NoResultFound:
                pass


        startrail_video_entry = self._miscDb.addStarTrailVideo(
            startrail_video_file,
            camera.id,
            startrail_video_metadata,
        )


        shutil.move(str(tmp_file), str(startrail_video_file))
        startrail_video_file.chmod(0o644)


        app.logger.info('Uploaded startrail: %s', startrail_video_file)

        return startrail_video_entry


class FileExists(Exception):
    pass


bp_syncapi_allsky.add_url_rule('/sync/v1/image', view_func=SyncApiImageView.as_view('syncapi_v1_image_view'), methods=['POST', 'PUT'])
bp_syncapi_allsky.add_url_rule('/sync/v1/video', view_func=SyncApiVideoView.as_view('syncapi_v1_video_view'), methods=['POST', 'PUT'])
bp_syncapi_allsky.add_url_rule('/sync/v1/keogram', view_func=SyncApiKeogramView.as_view('syncapi_v1_keogram_view'), methods=['POST', 'PUT'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrail', view_func=SyncApiStartrailView.as_view('syncapi_v1_startrail_view'), methods=['POST', 'PUT'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrailvideo', view_func=SyncApiStartrailVideoView.as_view('syncapi_v1_startrail_video_view'), methods=['POST', 'PUT'])

