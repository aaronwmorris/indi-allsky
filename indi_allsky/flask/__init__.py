import os
import time
import json
import mimetypes
from pathlib import Path
from logging.config import dictConfig

#from sqlalchemy.pool import NullPool
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from flask_login import LoginManager


try:
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth()
except ModuleNotFoundError:
    oauth = None


db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

from .views import bp_allsky  # noqa: E402
from .auth_views import bp_auth_allsky  # noqa: E402
from .syncapi_views import bp_syncapi_allsky  # noqa: E402
from .actionapi_views import bp_actionapi_allsky  # noqa: E402


dictConfig({
    'version' : 1,
    'formatters' : {
        'default' : {
            'format' : '[%(asctime)s] [%(levelname)s] %(processName)s-%(process)d %(module)s.%(funcName)s() [%(lineno)d]: %(message)s',
        },
        'syslog' : {
            'format' : '[%(levelname)s] %(processName)s-%(process)d %(module)s.%(funcName)s() [%(lineno)d]: %(message)s',
        },

    },
    'handlers' : {
        'wsgi' : {
            'class'     : 'logging.StreamHandler',
            'stream'    : 'ext://flask.logging.wsgi_errors_stream',
            'formatter' : 'default',
        },
        #'syslog_local6' : {
        #    'class'     : 'logging.handlers.SysLogHandler',
        #    'formatter' : 'syslog',
        #    'address'   : '/dev/log',
        #    'facility'  : 'local6',
        #},
        'syslog_local7' : {
            'class'     : 'logging.handlers.SysLogHandler',
            'formatter' : 'syslog',
            'address'   : '/dev/log',
            'facility'  : 'local7',
        },
    },
    'loggers' : {
        'root' : {
            'level'      : 'INFO',
            'handlers'   : ['wsgi'],
            'propagate'  : False,
        },
        'gunicorn.error' : {
            'level'      : 'INFO',
            'handlers'   : [os.getenv('GUNICORN_ERROR_LOG_HANDLER', 'syslog_local7')],
            'propagate'  : False,
        },
        'indi_allsky' : {
            'level'      : 'INFO',
            'handlers'   : [],  # indi_allsky handles it own logging
            'propagate'  : False,
        },
    }
})


def _sqlite_pragma_on_connect(dbapi_con, con_record):
    dbapi_con.execute('PRAGMA journal_mode=WAL')
    dbapi_con.execute('PRAGMA synchronous=NORMAL')
    #dbapi_con.execute('PRAGMA synchronous=OFF')  # dangerous but fast
    dbapi_con.execute('PRAGMA busy_timeout=20000')
    #dbapi_con.execute('PRAGMA encoding="UTF-8"')  # utf-8 is the default
    #dbapi_con.execute('PRAGMA read_uncommitted=ON')
    #dbapi_con.execute('PRAGMA foreign_keys=ON')


def create_app():
    """Construct the core application."""
    mimetypes.add_type('application/javascript', '.js')
    app = Flask(
        __name__,
        instance_relative_config=False,
    )

    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    flask_config = os.environ.get('INDI_ALLSKY_FLASK_CONFIG', '/etc/indi-allsky/flask.json')
    app.config.from_file(flask_config, load=json.load)

    #app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    #    "poolclass" : NullPool,  # disable connection pooling
    #}

    csrf.init_app(app)

    app.register_blueprint(bp_allsky)
    app.register_blueprint(bp_auth_allsky)
    app.register_blueprint(bp_syncapi_allsky)
    app.register_blueprint(bp_actionapi_allsky)

    csrf.exempt(bp_syncapi_allsky)  # disable CSRF for syncapi views
    csrf.exempt(bp_actionapi_allsky)  # disable CSRF for actionapi views

    db.init_app(app)
    migrate.init_app(app, db, directory=app.config['MIGRATION_FOLDER'])


    login_manager = LoginManager()
    login_manager.login_view = 'auth_indi_allsky.login_view'
    login_manager.init_app(app)


    if not isinstance(oauth, type(None)):
        oauth.init_app(app)


        with app.app_context():
            if app.config.get('OIDC_CLIENT_ID'):
                client_kwargs = {
                    'scope': app.config.get('OIDC_SCOPES', 'openid email profile'),
                }

                if app.config.get('OIDC_PKCE', True):
                    client_kwargs['code_challenge_method'] = 'S256'


                oidc_register_kwargs = {
                    'name' : 'oidc',
                    'client_id' : app.config.get('OIDC_CLIENT_ID'),
                    'client_secret' : app.config.get('OIDC_CLIENT_SECRET', '') if app.config.get('OIDC_CLIENT_SECRET') else None,
                    'server_metadata_url' : app.config.get('OIDC_DISCOVERY_ENDPOINT', ''),
                    'client_kwargs' : client_kwargs,
                }

                if app.config.get('OIDC_USERINFO_ENDPOINT'):
                    oidc_register_kwargs['userinfo_endpoint'] = app.config['OIDC_USERINFO_ENDPOINT']


                oauth.register(**oidc_register_kwargs)


    from .models import IndiAllSkyDbUserTable

    @login_manager.user_loader
    def load_user(user_id):
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return IndiAllSkyDbUserTable.query.get(int(user_id))


    @app.before_request
    def check_oidc_session():
        from flask_login import current_user, logout_user
        from flask import redirect, url_for, request, session

        if not current_user.is_authenticated:
            return

        # Skip for static files and common public assets to save processing
        if '/static/' in request.path or request.path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.css', '.js', '.mp4')):
            return

        user_data = dict(current_user.data) if current_user.data else {}
        if user_data.get('idp') == 'oidc':
            now_ts = int(time.time())
            session_sid = session.get('oidc_sid')
            session_login_time = session.get('oidc_login_time', 0)
            user_logged_out_at = user_data.get('oidc_logged_out_at', 0)
            revoked_sids = user_data.get('oidc_revoked_sids', {})

            is_revoked = False
            if session_sid and session_sid in revoked_sids:
                is_revoked = True
            elif user_logged_out_at and session_login_time <= user_logged_out_at:
                is_revoked = True

            session_timeout = app.config.get('OIDC_SESSION_TIMEOUT', 21600)  # default 6 hours
            if not is_revoked and session_timeout > 0:
                last_active = session.get('oidc_last_active') or session_login_time
                if last_active and (now_ts - last_active > session_timeout):
                    app.logger.info(
                        'Logging out user %s due to OIDC session inactivity timeout (%ds)',
                        current_user.username,
                        session_timeout,
                    )
                    is_revoked = True

            if is_revoked:
                app.logger.info('Logging out user %s due to OIDC session termination', current_user.username)
                session.clear()
                logout_user()

                if request.endpoint and request.endpoint.startswith('auth_indi_allsky.'):
                    return

                resp = redirect(url_for('auth_indi_allsky.login_view'))
                remember_cookie = app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
                resp.delete_cookie(
                    remember_cookie,
                    domain=app.config.get('REMEMBER_COOKIE_DOMAIN'),
                    path=app.config.get('REMEMBER_COOKIE_PATH', '/')
                )
                return resp

            # Update last activity timestamp for non-background polling requests
            if not request.path.endswith(('/notification', '/notifications', '/system_stats')):
                session['oidc_last_active'] = now_ts


    @app.after_request
    def prevent_caching(response):
        response.cache_control.no_store = True
        response.cache_control.no_cache = True
        return response


    with app.app_context():
        from sqlalchemy import event

        if db.engine.dialect.name == 'sqlite':
            event.listen(db.engine, 'connect', _sqlite_pragma_on_connect)

        #from . import views  # noqa: F401

        #db.create_all()  # Create sql tables for our data models

        return app


@bp_allsky.app_template_filter()
def basename(p):
    return Path(p).name
