import pytest
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
)


@pytest.fixture
def system_db(flask_app):
    with flask_app.app_context():
        db.session.query(IndiAllSkyDbCameraTable).delete()
        db.session.query(IndiAllSkyDbConfigTable).delete()
        db.session.query(IndiAllSkyDbUserTable).delete()
        db.session.commit()

        camera = IndiAllSkyDbCameraTable(
            id=1,
            name="main_camera",
            driver="indi_asi_ccd",
            friendlyName="Camera 1",
            uuid="33333333-3333-3333-3333-333333333333",
            latitude=-34.0,
            longitude=138.0,
            elevation=50,
            nightSunAlt=-6.0,
            local=True,
            hidden=False,
            utc_offset=36000.0,
            lensFocalLength=4.0,
            lensFocalRatio=2.0,
            lensImageCircle=180.0,
            cfa=None,
            owner="Admin",
            connectDate=db.func.now(),
            width=1920,
            height=1080,
            pixelSize=2.4,
            data={},
        )
        db.session.add(camera)

        config_entry = IndiAllSkyDbConfigTable(
            data={
                'WEBSITE': {'TITLE': 'indi-allsky'},
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FOLDER': '/tmp',
                'INDI_PORT': 7624,
                'ALLSKYMAP': {'API_URL': 'https://allsky-map.com'},
                'LENS_IMAGE_CIRCLE': 3000,
            },
            level="1.0",
            note='test config',
        )
        db.session.add(config_entry)

        user = IndiAllSkyDbUserTable(
            username="admin",
            password="password",
            email="admin@example.com",
            admin=True,
        )
        db.session.add(user)

        db.session.commit()
        yield camera
