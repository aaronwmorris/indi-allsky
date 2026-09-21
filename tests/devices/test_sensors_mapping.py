import pytest
from indi_allsky.sensors_mapping import (
    DEFAULT_FIXED_SLOTS,
    build_slot_label_map,
    format_named_sensors,
    get_latest_sensors_payload,
)


def test_build_slot_label_map():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_data_generator',
            'A_LABEL': 'Custom Test Sensor',
            'A_USER_VAR_SLOT': 'sensor_user_10',
            'A_TITLE_TEMPLATE': '{label:s} ({probe:s})',
        }
    }
    slot_map = build_slot_label_map(config)
    assert 0 in slot_map
    assert slot_map[0]['name'] == 'Camera Temperature'
    assert 10 in slot_map
    assert 'Custom Test Sensor' in slot_map[10]['name']


def test_format_named_sensors():
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_data_generator',
            'A_LABEL': 'Custom Test Sensor',
            'A_USER_VAR_SLOT': 'sensor_user_10',
        }
    }
    sensor_temp = [0.0] * 60
    sensor_user = [0.0] * 60
    sensor_user[0] = 25.5   # Camera temp
    sensor_user[10] = 42.0  # Custom sensor probe

    named = format_named_sensors(sensor_temp, sensor_user, config)
    assert 'camera_temp' in named
    assert named['camera_temp']['value'] == 25.5
    assert 10 in [meta['slot'] for meta in named.values()]


def test_get_latest_sensors_payload(flask_app, db):
    from indi_allsky.flask.models import IndiAllSkyDbImageTable
    db.session.query(IndiAllSkyDbImageTable).delete()
    db.session.commit()

    payload = get_latest_sensors_payload({})
    assert isinstance(payload, dict)
    assert 'sensors' in payload
    assert 'sensor_user' in payload
    assert 'sensor_temp' in payload
    assert payload['last_update'] is None
    assert payload['last_update_age_s'] is None


def test_get_latest_sensors_payload_with_image_record(flask_app, db):
    from datetime import datetime, date
    from indi_allsky.flask.models import IndiAllSkyDbCameraTable, IndiAllSkyDbImageTable

    cam = IndiAllSkyDbCameraTable(name="TestCam", uuid="test-cam-uuid")
    db.session.add(cam)
    db.session.commit()

    now = datetime.now()
    img = IndiAllSkyDbImageTable(
        camera_id=cam.id,
        filename="/tmp/test.jpg",
        createDate=now,
        dayDate=date.today(),
        night=True,
        exposure=5.0,
        gain=100.0,
        binmode=1,
        adu=50.0,
        data={
            'sensor_user_0': 21.5,
            'sensor_user_1': 55.0,
            'sensor_temp_0': 21.5,
        },
    )
    db.session.add(img)
    db.session.commit()

    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'sensor_data_generator',
            'A_LABEL': 'Ambient Sensor',
            'A_USER_VAR_SLOT': 'sensor_user_0',
        }
    }

    payload = get_latest_sensors_payload(config)
    assert payload['last_update'] == str(now)
    assert payload['last_update_age_s'] is not None
    assert payload['last_update_age_s'] >= 0
    assert payload['sensor_user'][0] == 21.5
    assert payload['sensor_user'][1] == 55.0
    assert payload['sensor_temp'][0] == 21.5
    assert 'sensor_a_add' in payload['sensors']
    assert payload['sensors']['sensor_a_add']['value'] == 21.5
