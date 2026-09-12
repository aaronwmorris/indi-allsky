from datetime import datetime, date
from passlib.hash import argon2
import pytest

from indi_allsky.flask.models import (
    IndiAllSkyDbUserTable,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbPanoramaImageTable,
)


@pytest.fixture(autouse=True)
def setup_camera_and_config(flask_app, db):
    with flask_app.app_context():
        cameras = IndiAllSkyDbCameraTable.query.all()
        if not cameras:
            camera = IndiAllSkyDbCameraTable(
                name='main_camera',
                driver='indi_simulator_ccd',
                friendlyName='Main Camera',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
                local=True,
            )
            db.session.add(camera)
        else:
            for cam in cameras:
                if cam.nightSunAlt is None:
                    cam.nightSunAlt = -6.0
                if cam.latitude is None:
                    cam.latitude = -34.9285
                if cam.longitude is None:
                    cam.longitude = 138.6007
                if cam.elevation is None:
                    cam.elevation = 50
                db.session.add(cam)

        config_entry = IndiAllSkyDbConfigTable.query.first()
        if not config_entry:
            config_entry = IndiAllSkyDbConfigTable(
                data={'WEBSITE': {'TITLE': 'indi-allsky'}},
                level=1,
                note='test',
            )
            db.session.add(config_entry)

        user = IndiAllSkyDbUserTable.query.filter_by(username='panoadmin').first()
        if not user:
            user = IndiAllSkyDbUserTable(
                username='panoadmin',
                password=argon2.hash('AdminSecret123!'),
                email='panoadmin@example.org',
                name='Pano Admin',
                admin=True,
                active=True,
            )
            db.session.add(user)
        else:
            user.password = argon2.hash('AdminSecret123!')
            user.admin = True
            user.active = True
            db.session.add(user)

        db.session.commit()


def test_ajax_image_exclude_and_panorama_sync(flask_app, db):
    with flask_app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        now = datetime.now()
        img = IndiAllSkyDbImageTable(
            camera_id=cam.id,
            filename='/tmp/pano_test_img.jpg',
            createDate=now,
            dayDate=date.today(),
            night=True,
            exposure=5.0,
            gain=100.0,
            binmode=1,
            adu=50.0,
            exclude=False,
        )
        db.session.add(img)
        db.session.commit()

        pano = IndiAllSkyDbPanoramaImageTable(
            camera_id=cam.id,
            filename='/tmp/pano_test.jpg',
            createDate=now,
            dayDate=date.today(),
            night=True,
            exposure=5.0,
            gain=100.0,
            binmode=1,
            exclude=False,
        )
        db.session.add(pano)
        db.session.commit()

        cam_id = cam.id
        img_id = img.id
        pano_id = pano.id

    client = flask_app.test_client()

    # 1. Unauthenticated request should be rejected
    res_unauth = client.post(
        '/indi-allsky/ajax/exclude',
        json={'CAMERA_ID': cam_id, 'EXCLUDE_IMAGE_ID': img_id, 'EXCLUDE_EXCLUDE': True},
    )
    assert res_unauth.status_code in (302, 400, 401)

    # 2. Login as admin
    res_login = client.post(
        '/indi-allsky/login',
        json={'USERNAME': 'panoadmin', 'PASSWORD': 'AdminSecret123!', 'NEXT': ''},
    )
    assert res_login.status_code == 200, res_login.get_json()

    # 3. Exclude image -> updates both image and panorama records
    res_exclude = client.post(
        '/indi-allsky/ajax/exclude',
        json={'CAMERA_ID': cam_id, 'EXCLUDE_IMAGE_ID': img_id, 'EXCLUDE_EXCLUDE': True},
    )
    assert res_exclude.status_code == 200

    with flask_app.app_context():
        updated_img = db.session.get(IndiAllSkyDbImageTable, img_id)
        updated_pano = db.session.get(IndiAllSkyDbPanoramaImageTable, pano_id)
        assert updated_img.exclude is True
        assert updated_pano.exclude is True

    # 4. Unexclude image -> updates both image and panorama records
    res_unexclude = client.post(
        '/indi-allsky/ajax/exclude',
        json={'CAMERA_ID': cam_id, 'EXCLUDE_IMAGE_ID': img_id, 'EXCLUDE_EXCLUDE': False},
    )
    assert res_unexclude.status_code == 200

    with flask_app.app_context():
        final_img = db.session.get(IndiAllSkyDbImageTable, img_id)
        final_pano = db.session.get(IndiAllSkyDbPanoramaImageTable, pano_id)
        assert final_img.exclude is False
        assert final_pano.exclude is False
