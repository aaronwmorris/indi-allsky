from unittest.mock import MagicMock, patch
from collections import namedtuple
import pytest
import dbus
import dbus.exceptions
from wtforms.validators import ValidationError

from indi_allsky.flask import forms as f_mod
from indi_allsky.flask.models import IndiAllSkyDbCameraTable

Field = namedtuple('Field', ['data'])


def test_login_form_validation(flask_app):
    with flask_app.test_request_context():
        form = f_mod.IndiAllskyLoginForm(data={
            "USERNAME": "testadmin",
            "PASSWORD": "SecurePassword123!",
            "NEXT": "",
        })
        assert form.validate() is True

        form_invalid = f_mod.IndiAllskyLoginForm(data={
            "USERNAME": "testadmin",
            "PASSWORD": "",
            "NEXT": "",
        })
        assert form_invalid.validate() is False
        assert "PASSWORD" in form_invalid.errors


def test_login_username_invalid():
    form = MagicMock()
    with pytest.raises(ValidationError, match='Invalid username'):
        f_mod.LOGIN__USERNAME_validator(form, Field('invalid user!'))


def test_user_email_invalid():
    form = MagicMock()
    with pytest.raises(ValidationError, match='not valid'):
        f_mod.USER__EMAIL_validator(form, Field('notanemail'))


def test_user_new_password_too_short():
    form = MagicMock()
    with pytest.raises(ValidationError, match='8 characters'):
        f_mod.USER__NEW_PASSWORD_validator(form, Field('short'))


def test_user_new_password_empty_returns():
    form = MagicMock()
    f_mod.USER__NEW_PASSWORD_validator(form, Field(''))
    f_mod.USER__NEW_PASSWORD_validator(form, Field(None))


def test_camera_select_form_validation(flask_app):
    with flask_app.test_request_context():
        form = f_mod.IndiAllskyCameraSelectForm(data={
            "CAMERA": "1",
        })
        assert form.validate() is False


def test_camera_select_form_friendly_name(flask_app, db):
    with flask_app.test_request_context():
        cam_friendly = IndiAllSkyDbCameraTable(
            name='g13_cam_friendly', uuid='g13-friendly-uuid',
            friendlyName='My Friendly Camera',
            latitude=0.0, longitude=0.0, local=True, hidden=False,
        )
        cam_no_friendly = IndiAllSkyDbCameraTable(
            name='g13_cam_no_friendly', uuid='g13-nofriendly-uuid',
            friendlyName=None,
            latitude=0.0, longitude=0.0, local=True, hidden=False,
        )
        db.session.add_all([cam_friendly, cam_no_friendly])
        db.session.commit()

        form = f_mod.IndiAllskyCameraSelectForm()
        choices = form.CAMERA_SELECT.choices
        labels = [label for _, label in choices]
        assert 'My Friendly Camera' in labels
        assert 'g13_cam_no_friendly' in labels


def test_set_timezone_dbus_exception(flask_app):
    with flask_app.test_request_context():
        with patch('dbus.SystemBus', side_effect=dbus.exceptions.DBusException('no dbus')):
            tz_form = f_mod.IndiAllskySetTimezoneForm()
            assert tz_form is not None


def test_user_info_form_password_validation(flask_app):
    with flask_app.test_request_context():
        import argon2 as _argon2_module
        ph = _argon2_module.PasswordHasher()
        old_password = 'OldPassword123!'
        old_hash = ph.hash(old_password)

        mock_user = MagicMock()
        mock_user.password = old_hash

        form = f_mod.IndiAllskyUserInfoForm(data={
            'NAME': 'Test User',
            'CURRENT_PASSWORD': 'wrongpassword',
            'NEW_PASSWORD': 'NewPassword456!',
            'NEW_PASSWORD2': 'NewPassword456!',
        })
        result = form.validate(mock_user)
        assert result is False
        assert any('not valid' in e for e in form.CURRENT_PASSWORD.errors)

        form2 = f_mod.IndiAllskyUserInfoForm(data={
            'NAME': 'Test User',
            'CURRENT_PASSWORD': '',
            'NEW_PASSWORD': 'NewPassword456!',
            'NEW_PASSWORD2': 'DifferentPassword!',
        })
        result2 = form2.validate(mock_user)
        assert result2 is False
        assert any('do not match' in e for e in form2.NEW_PASSWORD2.errors)

        form3 = f_mod.IndiAllskyUserInfoForm(data={
            'NAME': 'Test User',
            'CURRENT_PASSWORD': '',
            'NEW_PASSWORD': old_password,
            'NEW_PASSWORD2': old_password,
        })
        result3 = form3.validate(mock_user)
        assert result3 is False
        assert any('same as the old' in e for e in form3.NEW_PASSWORD.errors)
