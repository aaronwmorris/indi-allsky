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

    model = None


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
        elif request.method == 'DELETE':
            return self.delete()
        elif request.method == 'GET':
            return self.get()
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


        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def put(self):
        metadata = self.saveMetadata()
        media_file = self.saveFile()

        camera = self.getCamera(metadata['camera_uuid'])


        file_entry = self.processFile(camera, metadata, media_file, overwrite=True)


        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def delete(self):
        delete_id = request.json['id']

        try:
            self.deleteFile(delete_id)
        except FileMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({})


    def get(self):
        get_id = request.args.get('id')

        try:
            file_entry = self.getFile(get_id)
        except FileMissing:
            return jsonify({'error' : 'file_missing'}), 400

        return jsonify({
            'id'   : file_entry.id,
            'url'  : str(file_entry.getUrl(local=True)),
        })


    def processFile(self, camera, metadata, tmp_file, overwrite=False):
        d_dayDate = datetime.strptime(metadata['dayDate'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))
        if not date_folder.exists():
            date_folder.mkdir(mode=0o755)


        if metadata['night']:
            timeofday_str = 'night'
        else:
            timeofday_str = 'day'

        filename = date_folder.joinpath(self.filename_t.format(camera.id, d_dayDate.strftime('%Y%m%d'), timeofday_str, tmp_file.suffix))

        if not filename.exists():
            try:
                # delete old entry if it exists
                old_entry = self.model.query\
                    .filter(self.model.filename == str(filename))\
                    .one()

                app.logger.warning('Removing orphaned video entry')
                db.session.delete(old_entry)
                db.session.commit()
            except NoResultFound:
                pass

        else:
            if not overwrite:
                raise FileExists()

            app.logger.warning('Replacing file')
            filename.unlink()

            try:
                old_entry = self.model.query\
                    .filter(self.model.filename == str(filename))\
                    .one()

                app.logger.warning('Removing old entry')
                db.session.delete(old_entry)
                db.session.commit()
            except NoResultFound:
                pass


        new_entry = self._miscDb.addVideo(
            filename,
            camera.id,
            metadata,
        )

        shutil.move(str(tmp_file), str(filename))
        filename.chmod(0o644)

        app.logger.info('Uploaded file: %s', filename)

        return new_entry


    def deleteFile(self, entry_id):
        try:
            entry = self.model.query\
                .filter(self.model.id == entry_id)\
                .one()


            filename_p = Path(entry.filename)

            app.logger.warning('Deleting entry %d', entry.id)
            db.session.delete(entry)
            db.session.commit()
        except NoResultFound:
            raise FileMissing()


        try:
            filename_p.unlink()
        except FileNotFoundError:
            pass


    def getFile(self, entry_id):
        try:
            entry = self.model.query\
                .filter(self.model.id == entry_id)\
                .one()

        except NoResultFound:
            raise FileMissing()


        return entry


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

    model = IndiAllSkyDbImageTable
    filename_t = 'ccd{0:d}_{1:s}{2:s}'  # no dot for extension


    def processFile(self, camera, image_metadata, tmp_file, overwrite=False):
        createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(createDate, image_metadata['night'])

        date_str = createDate.strftime('%Y%m%d_%H%M%S')
        image_file = folder.joinpath(self.filename_t.format(camera.id, date_str, tmp_file.suffix))  # suffix includes dot


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

    model = IndiAllSkyDbVideoTable
    filename_t = 'allsky-timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'



class SyncApiKeogramView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbKeogramTable
    filename_t = 'allsky-keogram_ccd{0:d}_{1:s}_{2:s}{3:s}'


class SyncApiStartrailView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsTable
    filename_t = 'allsky-startrail_ccd{0:d}_{1:s}_{2:s}{3:s}'


class SyncApiStartrailVideoView(SyncApiBaseView):
    decorators = []

    model = IndiAllSkyDbStarTrailsVideoTable
    filename_t = 'allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'



class FileExists(Exception):
    pass


class FileMissing(Exception):
    pass


bp_syncapi_allsky.add_url_rule('/sync/v1/image', view_func=SyncApiImageView.as_view('syncapi_v1_image_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/video', view_func=SyncApiVideoView.as_view('syncapi_v1_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/keogram', view_func=SyncApiKeogramView.as_view('syncapi_v1_keogram_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrail', view_func=SyncApiStartrailView.as_view('syncapi_v1_startrail_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])
bp_syncapi_allsky.add_url_rule('/sync/v1/startrailvideo', view_func=SyncApiStartrailVideoView.as_view('syncapi_v1_startrail_video_view'), methods=['GET', 'POST', 'PUT', 'DELETE'])

