#import google.oauth2.credentials
import json

from flask import redirect
from flask import request
from flask import session
from flask import abort
from flask import url_for
from flask import current_app as app

from flask_login import login_required

from .base_views import BaseView


SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'


class YoutubeAuthorizeView(BaseView):
    decorators = [login_required]


    def dispatch_request(self):
        import google_auth_oauthlib.flow

        if not self.indi_allsky_config.get('YOUTUBE', {}).get('ENABLE'):
            abort(400, 'Youtube uploading not enabled')

        if not self.indi_allsky_config.get('YOUTUBE', {}).get('SECRETS_FILE'):
            abort(400, 'Client secrets not configured')

        client_secrets_file = self.indi_allsky_config.get('YOUTUBE', {}).get('SECRETS_FILE')

        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            client_secrets_file,
            scopes=SCOPES,
        )

        redirect_uri = url_for('indi_allsky.youtube_oauth2callback_view', _external=True)
        app.logger.info('Redirect URI: %s', redirect_uri)

        flow.redirect_uri = redirect_uri


        authorization_url, youtube_state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
        )

        session['youtube_state'] = youtube_state


        return redirect(authorization_url)


class YoutubeCallbackView(BaseView):
    decorators = [login_required]


    def dispatch_request(self):
        import google_auth_oauthlib.flow

        client_secrets_file = self.indi_allsky_config.get('YOUTUBE', {}).get('SECRETS_FILE')

        youtube_state = session['youtube_state']

        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            client_secrets_file,
            scopes=SCOPES,
            state=youtube_state,
        )

        flow.redirect_uri = url_for('indi_allsky.youtube_oauth2callback_view', _external=True)

        authorization_response = request.url
        flow.fetch_token(authorization_response=authorization_response)

        credentials_dict = self.credentials_to_dict(flow.credentials)

        credentials_json = json.dumps(credentials_dict)

        self._miscDb.setState('YOUTUBE_CREDS', credentials_json)


        return redirect(url_for('indi_allsky.config_view'))


    def credentials_to_dict(self, credentials):
        credentials = {
            'token'         : credentials.token,
            'refresh_token' : credentials.refresh_token,
            'token_uri'     : credentials.token_uri,
            'client_id'     : credentials.client_id,
            'client_secret' : credentials.client_secret,
            'scopes'        : credentials.scopes,
        }

        return credentials

