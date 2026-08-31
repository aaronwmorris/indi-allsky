import os
import pytest
from flask_migrate import upgrade, stamp
from indi_allsky.flask.models import db
from indi_allsky.version import __config_level__


def test_database_schema_and_tables_exist(flask_app, db):
    """Verify that all SQLAlchemy tables are registered and discoverable."""
    with flask_app.app_context():
        table_names = db.metadata.tables.keys()
        
        # Verify core tables are present in the SQLAlchemy metadata
        assert "user" in table_names
        assert "camera" in table_names
        assert "config" in table_names
        assert "image" in table_names
        assert "video" in table_names
        assert "notification" in table_names
        assert "taskqueue" in table_names


def test_camera_table_columns_parity(flask_app, db):
    """Ensure newly introduced columns exist on the camera model."""
    with flask_app.app_context():
        columns = [c.name for c in db.metadata.tables["camera"].columns]
        assert "serialNumber" in columns
        assert "nightSunAlt" in columns
        assert "friendlyName" in columns
        assert "driver" in columns
