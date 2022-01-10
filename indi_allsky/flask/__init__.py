import json
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

from .views import bp  # noqa


def create_app():
    """Construct the core application."""
    app = Flask(
        __name__,
        instance_relative_config=False,
    )
    app.config.from_file('../../flask.json', load=json.load)

    app.register_blueprint(bp)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        from . import views  # noqa
        db.create_all()  # Create sql tables for our data models

        return app
