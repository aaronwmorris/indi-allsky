import pytest
from indi_allsky.config import IndiAllSkyConfigUtil, IndiAllSkyConfig
from indi_allsky.version import __config_level__
from indi_allsky.flask.models import IndiAllSkyDbConfigTable


def test_config_bootstrap_and_level_update(flask_app, db):
    iacu = IndiAllSkyConfigUtil()
    iacu.image_folder = "/var/www/html/allsky/images"
    
    # Run bootstrap
    with flask_app.app_context():
        iacu.bootstrap()
        
        # Verify initial config entry exists
        config_entry = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        assert config_entry is not None
        assert config_entry.level == str(__config_level__)
        assert "INDI_SERVER" in config_entry.data


def test_config_update_level_execution(flask_app, db):
    iacu = IndiAllSkyConfigUtil()
    with flask_app.app_context():
        from indi_allsky.flask.models import IndiAllSkyDbUserTable
        from passlib.hash import argon2

        system_user = IndiAllSkyDbUserTable.query.filter_by(username="system").first()
        if not system_user:
            system_user = IndiAllSkyDbUserTable(
                username="system",
                password=argon2.hash("SystemPassword123!"),
                email="system@example.org",
                name="System",
                active=True,
                admin=True,
            )
            db.session.add(system_user)

        # Insert older config level
        old_config = IndiAllSkyDbConfigTable(
            level="19990101.0",
            note="Old version config",
            data={"INDI_SERVER": "localhost", "CCD_CONFIG": {}, "INDI_CONFIG_DEFAULTS": {}},
        )
        db.session.add(old_config)
        db.session.commit()

        # Update level
        iacu.update_level()

        # Verify updated config level matches current version
        latest = IndiAllSkyDbConfigTable.query.order_by(IndiAllSkyDbConfigTable.id.desc()).first()
        assert latest.level == str(__config_level__)
