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

from .base_views import BaseView

#from . import db

from .models import IndiAllSkyDbUserTable



bp_api_allsky = Blueprint(
    'wsapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class UploadApiView(BaseView):
    decorators = []


    def __init__(self, **kwargs):
        super(UploadApiView, self).__init__(**kwargs)

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
        # override in child class
        pass


    def saveFile(self):
        metadata_file = request.files['metadata']
        metadata_json = json.load(metadata_file)

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

        return metadata_json, Path(f_tmp_media.name)



    #def put(self):
    #    #media_file = request.files.get('media')
    #    pass


    def authorize(self):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            app.logger.error('Missing Authoriation header')
            return abort(400)

        try:
            bearer, user_apikey = auth_header.split(' ')
        except ValueError:
            app.logger.error('Malformed API key')
            return abort(400)


        try:
            username, apikey = user_apikey.split(':')
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

        hash1 = hashlib.sha256('{0:d}{1:s}'.format(time_floor, str(user.apikey)).encode()).hexdigest()
        if apikey != hash1:
            # we do not need to calculate the 2nd hash if the first one works
            hash2 = hashlib.sha256('{0:d}{1:s}'.format(time_floor + 1, str(user.apikey)).encode()).hexdigest()
            if apikey != hash2:
                return abort(400)


    def getImageFolder(self, exp_date, night):
        if night:
            # images should be written to previous day's folder until noon
            day_ref = exp_date - timedelta(hours=12)
            timeofday_str = 'night'
        else:
            # daytime
            # images should be written to current day's folder
            day_ref = exp_date
            timeofday_str = 'day'

        hour_str = exp_date.strftime('%d_%H')

        day_folder = self.image_dir.joinpath('{0:s}'.format(day_ref.strftime('%Y%m%d')), timeofday_str)
        if not day_folder.exists():
            day_folder.mkdir(mode=0o755, parents=True)

        hour_folder = day_folder.joinpath('{0:s}'.format(hour_str))
        if not hour_folder.exists():
            hour_folder.mkdir(mode=0o755)

        return hour_folder




class ImageUploadApiView(UploadApiView):
    filename_t = 'ccd{0:d}_{1:s}{2:s}'  # no dot for extension

    def post(self):
        image_metadata, image_file = self.saveFile()

        app.logger.info('Json: %s', image_metadata)
        app.logger.info('File: %s', image_file)


        createDate = datetime.fromtimestamp(image_metadata['createDate'])
        folder = self.getImageFolder(createDate, image_metadata['night'])

        date_str = createDate.strftime('%Y%m%d_%H%M%S')
        filename = folder.joinpath(self.filename_t.format(camera_id, date_str, image_file.suffix))  # suffix includes dot


        shutil.move(str(image_file), str(filename))


        filename.chmod(0o644)


        self._miscDb.addImage(
            filename,
            camera_id,
            image_metadata,
        )

        return jsonify({})



bp_api_allsky.add_url_rule('/upload/image', view_func=ImageUploadApiView.as_view('image_upload_view'), methods=['POST'])

