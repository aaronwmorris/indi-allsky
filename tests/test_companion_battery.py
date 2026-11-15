from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from indi_allsky.companion_battery import battery_reading


NOW = datetime(2026, 11, 15, 5, 45, tzinfo=timezone.utc)
CAMERA = SimpleNamespace(local=True, uuid='my-camera')
PROBES = {25: ('d', 'battery voltage (mv)'), 27: ('d', 'battery percent (%)'),
          28: ('d', 'remaining capacity (mah)')}
IMAGE = {'time_source': 'capture', 'captured_at': NOW.isoformat()}


def reading(metadata, **kwargs):
    return battery_reading(PROBES, metadata, kwargs.get('image', IMAGE), NOW,
                           kwargs.get('camera', CAMERA), kwargs.get('config', {}))


def test_relocated_gauge_preferred_over_capacity_and_unrelated_percentages():
    data = {'sensor_user_25': 13044, 'sensor_user_27': 15, 'sensor_user_28': 715}
    assert reading(data)['value'] == 15
    assert battery_reading({27: ('a', 'relative humidity')}, data, IMAGE, NOW, CAMERA, {}) is None
    assert battery_reading({28: PROBES[28]}, data, IMAGE, NOW, CAMERA, {}) == {}
    assert reading({**data, 'sensor_user_27': 0})['value'] == 0
    assert reading({key: 0 for key in data}) == {}
    assert reading({**data, 'sensor_valid_mask': 1 << 18}) == {}
    assert reading({**data, 'sensor_valid_mask': 0}) == {}


@pytest.mark.parametrize('bad', [None, -1, 101, float('inf'), True, 'invalid'])
def test_percentage_must_be_a_real_gauge_reading(bad):
    assert reading({'sensor_user_27': bad}) == {}


def test_recent_image_with_stale_sensor_and_expired_or_future_legacy_image():
    data = {'sensor_user_27': 15}
    assert reading({**data, 'sensor_last_good': [0, 0, 0, NOW.timestamp() - 130]}) == {}
    for seconds in (1, -130):
        assert reading(data, image={'time_source': 'capture',
                                    'captured_at': (NOW + timedelta(seconds=seconds)).isoformat()}) == {}
    assert reading(data, image=None) == {}


def test_unsaved_frame_uses_its_own_station_snapshot(tmp_path):
    source = {'time_source': 'file', 'captured_at': NOW.isoformat()}
    config = {'VARLIB_FOLDER': str(tmp_path)}
    status = tmp_path / 'indi_allsky_status.json'
    data = {'camera_uuid': CAMERA.uuid, 'time': str(int(NOW.timestamp())), 'sensor_user_27': 55}
    status.write_text(json.dumps(data))
    assert reading({'sensor_user_27': 1}, image=source, config=config)['value'] == 55
    assert reading({}, image=source, config=config, camera=SimpleNamespace(local=False)) == {}
    status.write_text(json.dumps({**data, 'camera_uuid': 'another-camera'}))
    assert reading(data, image=source, config=config) == {}
    status.write_text('{')
    assert reading(data, image=source, config=config) == {}
