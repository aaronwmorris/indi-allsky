import os
import sys
import tempfile
import json
from pathlib import Path
import pytest

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
    """Create a test Flask application configured with in-memory SQLite database."""
    app = create_app()

    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()

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
        _db.create_all()
        yield _db
        _db.session.rollback()

