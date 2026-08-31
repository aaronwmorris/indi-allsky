import io
import json
import time
import math
import hmac
import hashlib
from passlib.hash import argon2
import pytest
from cryptography.fernet import Fernet

from indi_allsky.flask.models import IndiAllSkyDbUserTable, IndiAllSkyDbCameraTable


@pytest.fixture
def sync_user(flask_app, db):
    """Create a user with encrypted apikey for testing HMAC auth."""
    with flask_app.app_context():
        password_key = flask_app.config['PASSWORD_KEY']
        f = Fernet(password_key.encode())
        raw_api_key = "test_sync_secret_api_key"
        encrypted_apikey = f.encrypt(raw_api_key.encode()).decode()

        user = IndiAllSkyDbUserTable.query.filter_by(username="syncuser").first()
        if not user:
            user = IndiAllSkyDbUserTable(
                username="syncuser",
                password=argon2.hash("SyncPassword123!"),
                email="syncuser@example.org",
                name="Sync User",
                active=True,
                admin=True,
                apikey=encrypted_apikey,
            )
            db.session.add(user)
            db.session.commit()
    return "syncuser", raw_api_key


def test_syncapi_missing_auth_header(flask_app):
    client = flask_app.test_client()
    data = {
        'metadata': (io.BytesIO(b'{"test": 1}'), 'metadata.json')
    }
    response = client.post('/indi-allsky/sync/v1/image', data=data)
    assert response.status_code == 400
    res_json = response.get_json()
    assert res_json.get('error') == 'authentication failed'


def test_syncapi_invalid_signature(flask_app, sync_user):
    username, _ = sync_user
    client = flask_app.test_client()
    metadata_bytes = b'{"test": 1}'
    headers = {
        'Authorization': f'Bearer {username}:badinvalidhmacsignature'
    }
    data = {
        'metadata': (io.BytesIO(metadata_bytes), 'metadata.json')
    }
    response = client.post('/indi-allsky/sync/v1/image', data=data, headers=headers)
    assert response.status_code == 400
    res_json = response.get_json()
    assert res_json.get('error') == 'authentication failed'


def test_syncapi_valid_hmac_authentication(flask_app, sync_user):
    username, raw_api_key = sync_user
    client = flask_app.test_client()
    media_data = b'dummy_image_data'
    metadata_bytes = json.dumps({'file_size': len(media_data), 'camera_uuid': 'dummy_uuid'}).encode()
    
    # Calculate valid HMAC for current time floor
    time_floor = math.floor(time.time() / 300)
    hmac_message = str(time_floor).encode() + metadata_bytes
    valid_hmac = hmac.new(
        raw_api_key.encode(),
        msg=hmac_message,
        digestmod=hashlib.sha3_512,
    ).hexdigest()

    headers = {
        'Authorization': f'Bearer {username}:{valid_hmac}'
    }
    data = {
        'metadata': (io.BytesIO(metadata_bytes), 'metadata.json'),
        'media': (io.BytesIO(media_data), 'image.jpg')
    }
    response = client.post('/indi-allsky/sync/v1/image', data=data, headers=headers)
    
    # HMAC passed and file size matched! (Returns 400 only because mock camera_uuid is unknown)
    res_json = response.get_json()
    assert res_json.get('error') == 'camera not found'
