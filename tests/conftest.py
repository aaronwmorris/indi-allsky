"""Pytest configuration and deterministic isolation for test suite."""

import os
import sys
import json
import tempfile
import types
import importlib.abc
import importlib.machinery
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Ensure test flask configuration is provided
_test_flask_cfg = Path(tempfile.gettempdir()) / "indi_allsky_test_flask.json"
_test_flask_cfg.write_text(
    json.dumps(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "MIGRATION_FOLDER": "/tmp/migrations",
            "SECRET_KEY": "TEST_SECRET_KEY",
            "PASSWORD_KEY": "TEST_PASSWORD_KEY",
            "INDI_ALLSKY_DOCROOT": "/tmp/allsky",
            "INDI_ALLSKY_IMAGE_FOLDER": "/tmp/allsky/images",
            "LOCAL_AUTH_ENABLE": True,
            "LOGIN_DISABLED": True,
            "WTF_CSRF_ENABLED": False,
        }
    )
)
os.environ['INDI_ALLSKY_FLASK_CONFIG'] = str(_test_flask_cfg)


class AutoMockFinder(importlib.abc.MetaPathFinder):
    """Dynamically provide mock modules for heavy astronomy and platform-specific dependencies."""

    mock_prefixes = (
        'astroalign',
        'astropy',
        'scipy',
        'sep',
        'ephem',
        'rawpy',
        'dbus',
        'simple_websocket',
        'passlib',
        'is_safe_url',
        'inotify',
        'paho',
        'bottleneck',
        'ccdproc',
        'pycurl',
        'photutils',
        'skyfield',
        'piexif',
        'imageio',
        'simplejpeg',
        'pygifsicle',
    )

    def find_spec(self, fullname, path, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in self.mock_prefixes):
            return importlib.machinery.ModuleSpec(fullname, AutoMockLoader(), is_package=True)
        return None


class AutoMockLoader(importlib.abc.Loader):
    def create_module(self, spec):
        m = types.ModuleType(spec.name)
        m.__path__ = []
        return m

    def exec_module(self, module):
        module.__getattr__ = lambda name: MagicMock()


sys.meta_path.append(AutoMockFinder())

import pytest


@pytest.fixture
def flask_app():
    from indi_allsky.flask import create_app, db as _db
    app = create_app()
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(flask_app):
    from indi_allsky.flask import db as _db
    return _db
