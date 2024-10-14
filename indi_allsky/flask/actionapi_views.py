import time
import random
from passlib.hash import argon2

from flask import request
from flask import Blueprint
from flask import jsonify
from flask import current_app as app

from .models import IndiAllSkyDbUserTable


bp_actionapi_allsky = Blueprint(
    'actionapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


from .base_views import BaseView


class ActionApiBaseView(BaseView):
    decorators = []


    def dispatch_request(self):
        try:
            self.authorize(request.json)
        except AuthenticationFailure as e:
            app.logger.error('Authentication failure: %s', str(e))
            return jsonify({'error' : 'authentication failed'}), 400


        if request.method == 'POST':
            return self.post()
        else:
            return jsonify({}), 400


    def authorize(self, data):
        # simple timing attack prevention
        random_sleep = random.randint(0, 250) / 1000.0
        time.sleep(random_sleep)


        username = data.get('username', '')
        password = data.get('password', '')


        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == username)\
            .first()


        if not user:
            app.logger.warning('Unknown user: %s', username)
            raise AuthenticationFailure('Unknown user')


        if not argon2.verify(password, user.password):
            app.logger.warning('User failed authentication: %s', user.username)
            raise AuthenticationFailure('Bad password')


    def post(self):
        # override in subclass
        return jsonify({}), 400


class AuthenticationFailure(Exception):
    pass

