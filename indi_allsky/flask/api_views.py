import time
#from datetime import datetime
#import math
import hashlib


from flask import request
from flask import Blueprint
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
    methods = ['POST']
    decorators = []


    def dispatch_request(self):
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


        time_floor = int(time.time() / 900) * 900

        hash1 = hashlib.sha256(str(time_floor) + str(user.apikey))
        if apikey != hash1:
            # we do not need to calculate the 2nd hash if the first one works
            hash2 = hashlib.sha256(str(time_floor + 1) + str(user.apikey))
            if apikey != hash2:
                return abort(400)


        # we are now authenticated
        metadata_file = request.files.get('metadata')
        media_file = request.files.get('media')


        return '', 204


bp_api_allsky.add_url_rule('/upload', view_func=UploadApiView.as_view('upload_view'))
