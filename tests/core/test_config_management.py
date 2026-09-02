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
