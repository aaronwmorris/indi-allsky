import json
from pathlib import Path
#from logging.config import dictConfig

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

from .views import bp  # noqa

### This causes problems with indi-allsky logging
#dictConfig({
#    'version': 1,
#    'formatters': {
#        'default': {
#            'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
#        },
#    },
#    'handlers': {
#        'wsgi': {
#            'class': 'logging.StreamHandler',
#            'stream': 'ext://flask.logging.wsgi_errors_stream',
#            'formatter': 'default',
#        },
#    },
#    'root': {
#        'level': 'INFO',
#        'handlers': ['wsgi']
#    },
#})


def create_app():
    """Construct the core application."""
    app = Flask(
        __name__,
        instance_relative_config=False,
    )

    p_flask_config = Path(__file__).parent.parent.parent.joinpath('flask.json').absolute()
    app.config.from_file(p_flask_config, load=json.load)

    csrf.init_app(app)

    app.register_blueprint(bp)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        from . import views  # noqa
        db.create_all()  # Create sql tables for our data models

        return app
