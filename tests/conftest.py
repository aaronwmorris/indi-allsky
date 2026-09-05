import os
import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

# Global PyIndi mock for environments without native INDI libraries
if 'PyIndi' not in sys.modules:
    mock_pyindi = MagicMock()
    mock_pyindi.BaseClient = object
    mock_pyindi.IPS_IDLE = 0
    mock_pyindi.IPS_OK = 1
    mock_pyindi.IPS_BUSY = 2
    mock_pyindi.IPS_ALERT = 3
    mock_pyindi.ISS_OFF = 0
    mock_pyindi.ISS_ON = 1
    mock_pyindi.ISR_1OFMANY = 0
    mock_pyindi.ISR_ATMOST1 = 1
    mock_pyindi.ISR_NOFMANY = 2
    mock_pyindi.INDI_NUMBER = 0
    mock_pyindi.INDI_SWITCH = 1
    mock_pyindi.INDI_TEXT = 2
    mock_pyindi.INDI_LIGHT = 3
    mock_pyindi.INDI_BLOB = 4
    sys.modules['PyIndi'] = mock_pyindi

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Prepare test configuration before any indi_allsky modules are imported
template_path = REPO_ROOT / "flask.json_template"
with open(template_path, "r", encoding="utf-8") as f:
    _test_config = json.load(f)

_tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
_tmp_db.close()

_test_config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_tmp_db.name}"
_test_config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
_test_config["WTF_CSRF_ENABLED"] = False
_test_config["TESTING"] = True
_test_config["SECRET_KEY"] = "dGVzdC1zZWNyZXQta2V5LTEyMzQ1Nzg5MDEyMzQ1Njc="
_test_config["PASSWORD_KEY"] = "k8Z_5n6f7q-q4M2_GjT5vB3-m9yW7xP2e1rL6sT0uV4="

_tmp_config = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump(_test_config, _tmp_config)
_tmp_config.close()
os.environ["INDI_ALLSKY_FLASK_CONFIG"] = _tmp_config.name

from indi_allsky.flask import create_app, db as _db
from indi_allsky.flask.models import *  # noqa: F401, F403


@pytest.fixture(scope="session")
def flask_app():
    """Create a test Flask application configured with SQLite database."""
    app = create_app()

    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()

    try:
        os.remove(_tmp_config.name)
        os.remove(_tmp_db.name)
    except OSError:
        pass


@pytest.fixture
def app(flask_app):
    """Alias for pytest-flask plugin compatibility."""
    return flask_app


@pytest.fixture
def db(flask_app):
    """Provide a clean database session for each test."""
    with flask_app.app_context():
        yield _db
        _db.session.rollback()
        _db.session.remove()


@pytest.fixture(autouse=True)
def clean_database_tables(flask_app):
    """Ensure a clean, isolated database state across tests."""
    with flask_app.app_context():
        yield
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            try:
                _db.session.execute(table.delete())
            except Exception:
                pass
        _db.session.commit()
        _db.session.remove()


@pytest.fixture
def base_config(tmp_path):
    """Return a standard full configuration dictionary for workers and processors."""
    import copy
    from indi_allsky.config import IndiAllSkyConfigBase

    cfg = copy.deepcopy(dict(IndiAllSkyConfigBase._base_config))
    cfg['IMAGE_FOLDER'] = str(tmp_path)
    cfg['VARLIB_FOLDER'] = str(tmp_path)
    cfg['LOCATION_LATITUDE'] = -34.9285
    cfg['LOCATION_LONGITUDE'] = 138.6007
    cfg['LOCATION_ELEVATION'] = 50
    cfg['NIGHT_SUN_ALT_DEG'] = -6.0
    cfg['CAMERA_INTERFACE'] = 'indi_simulator_ccd'
    return cfg


