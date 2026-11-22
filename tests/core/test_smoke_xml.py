import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet

if 'INDI_ALLSKY_FLASK_CONFIG' not in os.environ:
    _boot_dir = Path(tempfile.mkdtemp(prefix='indi_allsky_smoke_test_'))
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

import pytest
from indi_allsky.smoke import IndiAllskySmokeUpdate, NoSmokeData  # noqa: E402


def test_smoke_kml_parser_disables_entity_resolution(tmp_path):
    secret_f = tmp_path / 'secret.txt'
    secret_f.write_text('Smoke (Light)', encoding='utf-8')
    calc = IndiAllskySmokeUpdate({})
    calc.hms_kml_data = (
        f'<?xml version="1.0"?>'
        f'<!DOCTYPE kml [<!ENTITY ext SYSTEM "file://{secret_f}">]>'
        f'<kml xmlns="http://www.opengis.net/kml/2.2">'
        f'<Document><Folder><name>&ext;</name></Folder></Document>'
        f'</kml>'
    ).encode('utf-8')
    cam = SimpleNamespace(latitude=0.5, longitude=0.5)
    with pytest.raises(NoSmokeData):
        calc.update_na_hms(cam)
