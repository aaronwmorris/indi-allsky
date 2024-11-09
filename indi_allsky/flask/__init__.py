import os
import json
from pathlib import Path
from logging.config import dictConfig

#from sqlalchemy.pool import NullPool
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

from flask_login import LoginManager

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
    dbapi_con.execute('PRAGMA busy_timeout=20000')
    #dbapi_con.execute('PRAGMA read_uncommitted=ON')
    #dbapi_con.execute('PRAGMA foreign_keys=ON')


def create_app():
    """Construct the core application."""
    app = Flask(
        __name__,
        instance_relative_config=False,
    )

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

    from .models import IndiAllSkyDbUserTable


    @login_manager.user_loader
    def load_user(user_id):
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return IndiAllSkyDbUserTable.query.get(int(user_id))


    with app.app_context():
        from sqlalchemy import event

        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            event.listen(db.engine, 'connect', _sqlite_pragma_on_connect)

        #from . import views  # noqa: F401

        #db.create_all()  # Create sql tables for our data models

        return app


@bp_allsky.app_template_filter()
def basename(p):
    return Path(p).name
