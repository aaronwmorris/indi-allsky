import pytest
from unittest.mock import MagicMock, patch
from flask import Flask
from indi_allsky.flask.forms import (
    IndiAllskySetTimezoneForm,
    IndiAllskyIndiServerChangeForm,
    IndiAllskyConfigForm,
)


@pytest.fixture
def test_app():
    app = Flask('test_app')
    app.config['SECRET_KEY'] = 'test-secret-key'
    app.config['WTF_CSRF_ENABLED'] = False
    return app


def test_timezone_form_choices_are_tuples(test_app):
    with test_app.test_request_context():
        with patch('dbus.SystemBus') as mock_bus_cls:
            mock_bus = MagicMock()
            mock_bus_cls.return_value = mock_bus
            mock_timedate1 = MagicMock()
            mock_bus.get_object.return_value = mock_timedate1

            with patch('dbus.Interface') as mock_interface:
                mock_mgr = MagicMock()
                mock_mgr.ListTimezones.return_value = ['UTC', 'America/New_York', 'Europe/London']
                mock_interface.return_value = mock_mgr

                form = IndiAllskySetTimezoneForm()
                assert len(form.NEW_TIMEZONE.choices) == 3
                for choice in form.NEW_TIMEZONE.choices:
                    assert isinstance(choice, tuple)
                    assert len(choice) == 2

                # Verify rendering field produces valid HTML without AttributeError: 'NoneType' object has no attribute 'optgroup'
                rendered = form.NEW_TIMEZONE()
                assert '<select' in rendered
                assert 'value="UTC"' in rendered


def test_timezone_form_dbus_unavailable_fallback(test_app):
    import dbus.exceptions

    with test_app.test_request_context():
        with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('Bus unavailable')):
            form = IndiAllskySetTimezoneForm()
            assert len(form.NEW_TIMEZONE.choices) == 1
            for choice in form.NEW_TIMEZONE.choices:
                assert isinstance(choice, tuple)
                assert len(choice) == 2

            rendered = form.NEW_TIMEZONE()
            assert 'D-Bus Unavailable' in rendered


def test_indiserver_change_form_choices_are_tuples(test_app):
    with test_app.test_request_context():
        form = IndiAllskyIndiServerChangeForm()
        for choice in form.CAMERA_SERVER_SELECT.choices:
            assert isinstance(choice, tuple)
            assert len(choice) == 2

        for choice in form.GPS_SERVER_SELECT.choices:
            assert isinstance(choice, tuple)
            assert len(choice) == 2

        rendered_cam = form.CAMERA_SERVER_SELECT()
        assert '<select' in rendered_cam


def test_config_form_grouped_choices_are_tuples(test_app):
    for group_name, items in IndiAllskyConfigForm.CUSTOM_CHART_choices.items():
        assert isinstance(items, (list, tuple))
        for item in items:
            assert isinstance(item, tuple), f'Item {item} in CUSTOM_CHART_choices[{group_name}] is not a tuple'
            assert len(item) == 2

    for group_name, items in IndiAllskyConfigForm.SENSOR_SLOT_choices.items():
        assert isinstance(items, (list, tuple))
        for item in items:
            assert isinstance(item, tuple), f'Item {item} in SENSOR_SLOT_choices[{group_name}] is not a tuple'
            assert len(item) == 2
