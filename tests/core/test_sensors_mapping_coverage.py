from unittest.mock import patch, MagicMock
import pytest

from indi_allsky.sensors_mapping import (
    build_slot_label_map,
    format_named_sensors,
    get_latest_sensors_payload,
)


def test_build_slot_label_map_exception():
    # Pass an invalid classname to trigger AttributeError in build_slot_label_map (lines 103-104)
    config = {
        'TEMP_SENSOR': {
            'A_CLASSNAME': 'NonExistentSensorClass12345',
            'A_LABEL': 'Bad Sensor',
        }
    }
    slot_map = build_slot_label_map(config)
    # The default fixed slots 0-9 should still be present
    assert 0 in slot_map
    assert 1 in slot_map


def test_get_latest_sensors_payload_exception():
    # Mock IndiAllSkyDbImageTable to raise an Exception to trigger lines 155-156
    with patch('indi_allsky.flask.models.IndiAllSkyDbImageTable') as mock_table:
        mock_table.query.order_by.side_effect = RuntimeError("Database connection failed")
        
        payload = get_latest_sensors_payload()
        assert payload['last_update'] is None
        assert payload['last_update_age_s'] is None
        assert payload['sensor_user'] == [0.0] * 60
        assert payload['sensor_temp'] == [0.0] * 60
        assert 'sensors' in payload
