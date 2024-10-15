import time
import random
from passlib.hash import argon2

from flask import request
from flask import Blueprint
from flask import jsonify
from flask import current_app as app

from . import db

from .models import IndiAllSkyDbUserTable
from .models import IndiAllSkyDbTaskQueueTable

from .models import TaskQueueQueue
from .models import TaskQueueState

from .base_views import BaseView


bp_actionapi_allsky = Blueprint(
    'actionapi_indi_allsky',
    __name__,
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
)


class ActionApiBaseView(BaseView):
    decorators = []


    def dispatch_request(self):
        try:
            self.authorize(request.json)
        except AuthenticationFailure as e:
            app.logger.error('Authentication failure: %s', str(e))
            return jsonify({'error' : 'authentication failed'}), 400
        except PermissionDenied as e:
            app.logger.error('Permission denied: %s', str(e))
            return jsonify({'error' : 'permission denied'}), 400


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
            raise AuthenticationFailure('Unknown user: {0:s}'.format(username))

        if not argon2.verify(password, user.password):
            raise AuthenticationFailure('User failed authentication: {0:s}'.format(username))


        if not user.is_admin:
            raise PermissionDenied('Permission Denied for user: {0:s}'.format(username))


    def post(self):
        # override in subclass
        return jsonify({}), 400


class PauseActionApiView(ActionApiBaseView):
    decorators = []

    def post(self):
        if self.indi_allsky_config.get('CAPTURE_PAUSE'):
            message = {
                'message' : 'Capture is already paused',
            }
            return jsonify(message), 200


        task_pause = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                'action'    : 'setpaused',
                'pause'     : True,
            },
        )

        db.session.add(task_pause)
        db.session.commit()

        message = {
            'message' : 'Pause task created.',
        }

        return jsonify(message), 201


class UnpauseActionApiView(ActionApiBaseView):
    decorators = []

    def post(self):
        if not self.indi_allsky_config.get('CAPTURE_PAUSE'):
            message = {
                'message' : 'Capture is already unpaused',
            }
            return jsonify(message), 200


        task_unpause = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.MAIN,
            state=TaskQueueState.MANUAL,
            priority=100,
            data={
                'action'    : 'setpaused',
                'pause'     : False,
            },
        )

        db.session.add(task_unpause)
        db.session.commit()

        message = {
            'message' : 'Unpause task created.',
        }

        return jsonify(message), 201


class AuthenticationFailure(Exception):
    pass


class PermissionDenied(Exception):
    pass


bp_actionapi_allsky.add_url_rule('/action/pause', view_func=PauseActionApiView.as_view('actionapi_pause_view'), methods=['POST'])
bp_actionapi_allsky.add_url_rule('/action/unpause', view_func=UnpauseActionApiView.as_view('actionapi_unpause_view'), methods=['POST'])

