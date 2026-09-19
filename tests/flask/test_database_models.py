from passlib.hash import argon2
from indi_allsky.flask.models import (
    IndiAllSkyDbUserTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)


def test_user_model_creation(db):
    hashed_password = argon2.hash("SecurePassword123!")
    user = IndiAllSkyDbUserTable(
        username="testadmin",
        password=hashed_password,
        email="testadmin@example.org",
        name="Test Admin",
        active=True,
        admin=True,
        staff=True,
    )
    db.session.add(user)
    db.session.commit()

    queried = IndiAllSkyDbUserTable.query.filter_by(username="testadmin").first()
    assert queried is not None
    assert queried.email == "testadmin@example.org"
    assert queried.admin is True
    assert argon2.verify("SecurePassword123!", queried.password) is True
    assert argon2.verify("WrongPassword", queried.password) is False


def test_camera_model_with_serial_number(db):
    camera = IndiAllSkyDbCameraTable(
        name="test_camera_1",
        driver="indi_simulator_ccd",
        friendlyName="Main AllSky Camera",
        serialNumber="ZWO-ASI-12345678",
        latitude=-34.9285,
        longitude=138.6007,
        elevation=50,
        nightSunAlt=-6.0,
    )
    db.session.add(camera)
    db.session.commit()

    queried = IndiAllSkyDbCameraTable.query.filter_by(name="test_camera_1").first()
    assert queried is not None
    assert queried.serialNumber == "ZWO-ASI-12345678"
    assert queried.latitude == -34.9285


def test_config_model_storage(db):
    config_entry = IndiAllSkyDbConfigTable(
        level="20260826.0",
        note="Initial test configuration",
        data={
            "CAMERA_INTERFACE": "indi",
            "LOCATION_LATITUDE": -34.9285,
            "LOCATION_LONGITUDE": 138.6007,
        },
    )
    db.session.add(config_entry)
    db.session.commit()

    queried = IndiAllSkyDbConfigTable.query.filter_by(level="20260826.0").first()
    assert queried is not None
    assert queried.data["CAMERA_INTERFACE"] == "indi"


def test_task_queue_model(db):
    task = IndiAllSkyDbTaskQueueTable(
        queue=TaskQueueQueue.MAIN,
        state=TaskQueueState.QUEUED,
        priority=100,
        data={"action": "test_task"},
    )
    db.session.add(task)
    db.session.commit()

    queried = IndiAllSkyDbTaskQueueTable.query.filter_by(id=task.id).first()
    assert queried is not None
    assert queried.state == TaskQueueState.QUEUED
    assert queried.data["action"] == "test_task"
