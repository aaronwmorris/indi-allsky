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

from .. import constants

from .base_views import BaseView

#from . import db

from .models import IndiAllSkyDbUserTable
from .models import IndiAllSkyDbCameraTable

#from sqlalchemy.orm.exc import NoResultFound


bp_syncapi_allsky = Blueprint(
    'syncapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class SyncApiView(BaseView):
    decorators = []

    image_filename_t = 'ccd{0:d}_{1:s}{2:s}'  # no dot for extension


    def __init__(self, **kwargs):
        super(SyncApiView, self).__init__(**kwargs)

        if self.indi_allsky_config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.indi_allsky_config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.parent.joinpath('html', 'images').absolute()


    def dispatch_request(self):
        self.authorize()

        # we are now authenticated

        if request.method == 'POST':
            return self.post()
        #elif request.method == 'PUT':
        #    return self.put(entry_id)
        else:
            return jsonify({}), 400


    def post(self):
        metadata = self.saveMetadata()
        media_file = self.saveFile()

        camera = self.getCamera(metadata['camera_uuid'])


        if metadata['type'] == constants.IMAGE:
            self.processImage(camera, metadata, media_file)

        return jsonify({})



    def processImage(self, camera, image_metadata, tmp_file):
        createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(createDate, image_metadata['night'])

        date_str = createDate.strftime('%Y%m%d_%H%M%S')
        image_file = folder.joinpath(self.image_filename_t.format(camera.id, date_str, tmp_file.suffix))  # suffix includes dot


        if image_file.exists():
            tmp_file.unlink()
            return abort(400)


        shutil.move(str(tmp_file), str(image_file))


        image_file.chmod(0o644)


        self._miscDb.addImage(
            image_file,
            camera.id,
            image_metadata,
        )


    def processVideo(self, camera, video_metadata, tmp_file):
        d_dayDate = datetime.strptime(video_metadata['timespec'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))


        video_file = date_folder.joinpath('allsky-timelapse_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), video_metadata['timeofday'], tmp_file.suffix))

        if video_file.exists():
            tmp_file.unlink()
            return abort(400)


        shutil.move(str(tmp_file), str(video_file))


        # Create DB entry before creating file
        self._miscDb.addVideo(
            video_file,
            camera.id,
            video_metadata,
        )


    def processKeogram(self, camera, keogram_metadata, tmp_file):
        d_dayDate = datetime.strptime(keogram_metadata['timespec'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))


        keogram_file = date_folder.joinpath('allsky-keogram_ccd{0:d}_{1:s}_{2:s}{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), keogram_metadata['timeofday'], tmp_file.suffix))


        if keogram_file.exists():
            tmp_file.unlink()
            return abort(400)


        shutil.move(str(tmp_file), str(keogram_file))


        self._miscDb.addKeogram(
            keogram_file,
            camera.id,
            keogram_metadata,
        )


    def processStartrail(self, camera, startrail_metadata, tmp_file):
        d_dayDate = datetime.strptime(startrail_metadata['timespec'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))


        startrail_file = date_folder.joinpath('allsky-startrail_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), startrail_metadata['timeofday'], self.config['IMAGE_FILE_TYPE']))


        if startrail_file.exists():
            tmp_file.unlink()
            return abort(400)


        shutil.move(str(tmp_file), str(startrail_file))


        self._miscDb.addStarTrail(
            startrail_file,
            camera.id,
            startrail_metadata,
        )


    def processStartrailVideo(self, camera, startrail_video_metadata, tmp_file):
        d_dayDate = datetime.strptime(startrail_video_metadata['timespec'], '%Y%m%d').date()

        date_folder = self.image_dir.joinpath(d_dayDate.strftime('%Y%m%d'))


        startrail_video_file = date_folder.joinpath('allsky-startrail_timelapse_ccd{0:d}_{1:s}_{2:s}.{3:s}'.format(camera.id, d_dayDate.strftime('%Y%m%d'), startrail_video_metadata['timeofday'], tmp_file.suffix))


        if startrail_video_file.exists():
            tmp_file.unlink()
            return abort(400)


        shutil.move(str(tmp_file), str(startrail_video_file))


        self._miscDb.addStarTrailVideo(
            startrail_video_file,
            camera.id,
            startrail_video_metadata,
        )


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


bp_syncapi_allsky.add_url_rule('/sync/v1', view_func=SyncApiView.as_view('syncapi_v1_view'), methods=['POST'])

