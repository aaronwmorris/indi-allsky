import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

if 'INDI_ALLSKY_FLASK_CONFIG' not in os.environ:
    _boot_dir = Path(tempfile.mkdtemp(prefix='indi_allsky_ws_test_'))
    _boot_cfg = {
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{_boot_dir / "boot.sqlite"}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'MIGRATION_FOLDER': str(_boot_dir / 'migrations'),
        'SECRET_KEY': 'boot-secret',
        'PASSWORD_KEY': Fernet.generate_key().decode(),
        'INDI_ALLSKY_DOCROOT': str(_boot_dir / 'html'),
        'INDI_ALLSKY_IMAGE_FOLDER': str(_boot_dir / 'images'),
        'LOGIN_DISABLED': False,
        'INDI_ALLSKY_AUTH_ALL_VIEWS': False,
        'INDI_ALLSKY_AUTH_MEDIA_VIEWS': False,
    }
    _boot_json = _boot_dir / 'flask.json'
    _boot_json.write_text(json.dumps(_boot_cfg), encoding='utf-8')
    os.environ['INDI_ALLSKY_FLASK_CONFIG'] = str(_boot_json)

from indi_allsky.config import IndiAllSkyConfigBase  # noqa: E402
from indi_allsky.flask import create_app, db  # noqa: E402
from indi_allsky.flask.models import IndiAllSkyDbConfigTable, IndiAllSkyDbStateTable  # noqa: E402


def test_ws_rejects_mismatched_origin():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        cfg = IndiAllSkyDbConfigTable(data=dict(IndiAllSkyConfigBase._base_config), level='1.0', note='ws-test')
        db.session.add(cfg)
        db.session.flush()
        db.session.add(IndiAllSkyDbStateTable(key='CONFIG_ID', value=str(cfg.id)))
        db.session.commit()

        client = app.test_client()
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Origin': 'https://evil.example',
        }
        assert client.get('/indi-allsky/ws/events', headers=headers).status_code == 403
        assert client.get('/indi-allsky/ws/control', headers=headers).status_code == 403
        db.session.remove()
        db.drop_all()
