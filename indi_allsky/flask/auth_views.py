import time
import random
import string
from datetime import datetime

from passlib.hash import argon2

from flask import request
from flask import session
from flask import Blueprint
from flask import redirect
from flask import url_for
from is_safe_url import is_safe_url
from flask import abort
#from flask import render_template
#from flask import flash
from flask import jsonify
from flask import current_app as app

from flask_login import login_user
from flask_login import logout_user
#from flask_login import login_required
from flask_login import current_user

from .base_views import BaseView
from .base_views import TemplateView

from . import db
from . import oauth

from .models import IndiAllSkyDbUserTable

from .forms import IndiAllskyLoginForm


bp_auth_allsky = Blueprint(
    'auth_indi_allsky',
    __name__,
    template_folder='templates',
    static_folder='static',
    #url_prefix='/',  # wsgi
    url_prefix='/indi-allsky',  # gunicorn
    static_url_path='static',
)


class LoginView(TemplateView):
    methods = ['GET', 'POST']
    decorators = []

    def get_context(self):
        context = super(LoginView, self).get_context()

        context['form_login'] = IndiAllskyLoginForm(NEXT=request.args.get('next', ''))
        context['oidc_enabled'] = app.config.get('OIDC_ENABLE', False)
        context['oidc_provider_name'] = app.config.get('OIDC_PROVIDER_NAME', '[Configure Provider Name]')
        context['oidc_logo_url'] = app.config.get('OIDC_LOGO_URL', '')
        context['local_auth_enable'] = app.config.get('LOCAL_AUTH_ENABLE', True)

        return context


    def dispatch_request(self):
        if request.method == 'POST':
            return self.post()
        elif request.method == 'GET':
            return self.get()
        else:
            return abort(400)


    def get(self):
        if current_user.is_authenticated:
            return redirect(url_for('indi_allsky.index_view'))

        if app.config.get('OIDC_ENABLE') and app.config.get('OIDC_AUTO_LOGIN'):
            return redirect(url_for('auth_indi_allsky.oidc_login_view', next=request.args.get('next', '')))

        return super(LoginView, self).dispatch_request()


    def post(self):
        # simple timing attack prevention
        random_sleep = random.randint(0, 250) / 1000.0
        time.sleep(random_sleep)

        form_login = IndiAllskyLoginForm(data=request.json)

        if not form_login.validate():
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Please fix errors above']
            return jsonify(form_errors), 400


        user = IndiAllSkyDbUserTable.query\
            .filter(IndiAllSkyDbUserTable.username == request.json['USERNAME'])\
            .first()


        if not user:
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Invalid username or password']
            app.logger.error('User not found: %s', request.json['USERNAME'])
            return jsonify(form_errors), 400


        if not argon2.verify(request.json['PASSWORD'], user.password):
            #app.logger.info('Password entered: %s', request.json['PASSWORD'])
            app.logger.warning('User failed authentication: %s', user.username)
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['Invalid username or password']
            return jsonify(form_errors), 400


        if not user.is_active:
            form_errors = form_login.errors  # this must be a property
            form_errors['form_global'] = ['User is disabled']
            return jsonify(form_errors), 400


        app.logger.info('User successfully authenticated: %s', user.username)

        session.permanent = True
        login_user(user, remember=True)


        # record the login
        if request.headers.get('X-Forwarded-For'):
            remote_addr = request.headers.get('X-Forwarded-For')
        else:
            remote_addr = request.remote_addr


        if user.data:
            user_data = dict(user.data)
        else:
            user_data = dict()


        now = datetime.now()
        user.loginDate = now
        user.loginIp = remote_addr

        user_data['idp'] = 'local'
        user.data = user_data

        db.session.commit()


        next_url = request.json['NEXT']

        if not next_url or not is_safe_url(next_url, {'*'}):
            app.logger.warning('Next URL failed validation: %s', next_url)
            data = {
                'redirect' : url_for('indi_allsky.index_view'),
            }
            return jsonify(data)


        data = {
            'redirect' : next_url,
        }
        return jsonify(data)


class OIDCLoginView(BaseView):
    decorators = []

    def dispatch_request(self):
        if not hasattr(oauth, 'oidc'):
            app.logger.error('OIDC login attempted but oidc client is not registered')
            return redirect(url_for('auth_indi_allsky.login_view'))

        redirect_uri = url_for('auth_indi_allsky.oidc_callback_view', _external=True)

        # Store 'next' URL in session for the callback
        next_url = request.args.get('next')
        if next_url and is_safe_url(next_url, {request.host}):
            session['oidc_next'] = next_url

        try:
            return oauth.oidc.authorize_redirect(redirect_uri)
        except Exception as e:
            app.logger.error('Error during OIDC redirect: %s', str(e))
            return redirect(url_for('auth_indi_allsky.login_view'))


class OIDCCallbackView(BaseView):
    decorators = []

    def dispatch_request(self):
        if not hasattr(oauth, 'oidc'):
            return abort(404)

        # Check if this is a logout callback (no code but has state or just returning from IdP)
        if 'code' not in request.args:
            try:
                oauth.oidc.validate_logout_response()
            except Exception as e:
                # If validation fails, it might just be a direct redirect without state,
                # we still want to land on the index page.
                app.logger.debug('OIDC logout callback validation: %s', str(e))

            return redirect(url_for('indi_allsky.index_view'))

        try:
            token = oauth.oidc.authorize_access_token()
            #app.logger.info('Token: %s', token)

            session['oidc_id_token'] = token.get('id_token')  # Store for logout hint
            session['oidc_expires_at'] = token.get('expires_at')

            oidc_user_info = token.get('userinfo')
            if not oidc_user_info:
                oidc_user_info = oauth.oidc.userinfo()

            #app.logger.info('User Info: %s', oidc_user_info)

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'error'):
                error_msg = f"{e.error}: {getattr(e, 'description', 'No description')}"

            app.logger.error('OIDC callback failed to exchange token: %s', error_msg)
            return redirect(url_for('auth_indi_allsky.login_view'))


        oidc_username = oidc_user_info.get(app.config.get('OIDC_USERNAME_ATTRIBUTE', 'email'))
        oidc_user_groups = oidc_user_info.get('groups', [])


        if not oidc_username:
            app.logger.error('OIDC login failed: No username provided by identity provider')
            return redirect(url_for('auth_indi_allsky.login_view'))


        # only allow members of these groups to login (if defined)
        oidc_allowed_groups = app.config.get('OIDC_ALLOWED_GROUPS', [])
        if oidc_allowed_groups:
            if isinstance(oidc_user_groups, list):
                if not set(oidc_allowed_groups).intersection(set(oidc_user_groups)):
                    session.clear()  # force delete session (prevents incomplete session
                    app.logger.error('OIDC User not allowed to login: %s', oidc_username)
                    return redirect(url_for('auth_indi_allsky.login_view'))
            elif isinstance(oidc_user_groups, str):
                # Sometimes groups come as a space-separated string
                if not set(oidc_allowed_groups).intersection(set(oidc_user_groups.split())):
                    session.clear()  # force delete session (prevents incomplete session
                    app.logger.error('OIDC User not allowed to login: %s', oidc_username)
                    return redirect(url_for('auth_indi_allsky.login_view'))
            else:
                session.clear()  # force delete session (prevents incomplete session
                app.logger.error('Unhandled group variable type: %s', type(oidc_user_groups))
                return redirect(url_for('auth_indi_allsky.login_view'))


        # only allow these users to login (if defined)
        oidc_allowed_users = app.config.get('OIDC_ALLOWED_USERS')
        if oidc_allowed_users:
            if oidc_username not in oidc_allowed_users:
                session.clear()  # force delete session (prevents incomplete session
                app.logger.error('OIDC User not allowed to login: %s', oidc_username)
                return redirect(url_for('auth_indi_allsky.login_view'))


        # Find or Create User
        user = IndiAllSkyDbUserTable.query.filter_by(username=oidc_username).first()

        if not user:
            user = IndiAllSkyDbUserTable(
                username=oidc_username,
                email=oidc_user_info.get('email', ''),
                password=argon2.hash(''.join(random.choices(string.ascii_letters + string.digits, k=32))),
                name=oidc_user_info.get('name', ''),
                active=True,
                staff=True,
            )
            db.session.add(user)

            user_data = dict()
            app.logger.info('Created new OIDC user: %s', oidc_username)
        else:
            # user exists
            if user.data:
                user_data = dict(user.data)
            else:
                user_data = dict()


        # grant admin access to members of these groups (if defined)
        oidc_admin_groups = app.config.get('OIDC_ADMIN_GROUPS', [])
        if oidc_admin_groups:
            if isinstance(oidc_user_groups, list):
                user.admin = bool(set(oidc_admin_groups).intersection(set(oidc_user_groups)))
            elif isinstance(oidc_user_groups, str):
                # Sometimes groups come as a space-separated string
                user.admin = bool(set(oidc_admin_groups).intersection(set(oidc_user_groups.split())))
            else:
                app.logger.error('Unhandled group variable type: %s', type(oidc_user_groups))


        # manual list of admin users
        oidc_admin_users = app.config.get('OIDC_ADMIN_USERS')
        if oidc_admin_users:
            user.admin = oidc_username in oidc_admin_users


        if request.headers.get('X-Forwarded-For'):
            remote_addr = request.headers.get('X-Forwarded-For')
        else:
            remote_addr = request.remote_addr


        session.permanent = True
        login_user(user, remember=True)


        now = datetime.now()
        user.loginDate = now
        user.loginIp = remote_addr

        user_data['idp'] = 'oidc'
        user_data['oidc_token'] = token
        user.data = user_data

        db.session.commit()


        # Redirect to original destination
        next_url = session.pop('oidc_next', None)
        if not next_url or not is_safe_url(next_url, {'*'}):
            next_url = url_for('indi_allsky.index_view')

        return redirect(next_url)


class LogoutView(BaseView):
    decorators = []  # manually handle if user is logged in

    def dispatch_request(self):
        id_token = session.pop('oidc_id_token', None)

        if not current_user.is_authenticated:
            return redirect(url_for('indi_allsky.index_view'))


        if current_user.data:
            current_user_data = dict(current_user.data)
        else:
            current_user_data = dict()


        # If session hint is missing, try to get it from the user record
        if not id_token and current_user_data.get('oidc_token'):
            id_token = current_user_data['oidc_token'].get('id_token')

        # Clear token from DB on logout for security
        if current_user_data.get('oidc_token'):
            current_user_data['oidc_token'] = None
            current_user.data = current_user_data
            db.session.commit()


        logout_user()


        # Check if OIDC logout should be initiated
        if app.config.get('OIDC_ENABLE') and id_token and hasattr(oauth, 'oidc'):
            try:
                return oauth.oidc.logout_redirect(
                    post_logout_redirect_uri=url_for('auth_indi_allsky.oidc_callback_view', _external=True),
                    id_token_hint=id_token
                )
            except Exception as e:
                app.logger.error('OIDC logout redirect failed: %s', str(e))

        return redirect(url_for('indi_allsky.index_view'))


bp_auth_allsky.add_url_rule('/login', view_func=LoginView.as_view('login_view', template_name='login.html'))
bp_auth_allsky.add_url_rule('/oidc/login', view_func=OIDCLoginView.as_view('oidc_login_view'))
bp_auth_allsky.add_url_rule('/oidc/callback', view_func=OIDCCallbackView.as_view('oidc_callback_view'))
bp_auth_allsky.add_url_rule('/logout', view_func=LogoutView.as_view('logout_view'))
