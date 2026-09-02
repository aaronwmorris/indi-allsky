import pytest
from werkzeug.datastructures import MultiDict
from indi_allsky.flask.forms import (
    LOGIN__USERNAME_validator,
    IndiAllskyLoginForm,
    IndiAllskyCameraSelectForm,
)
from wtforms.validators import ValidationError


def test_login_username_validator_valid():
    class DummyField:
        data = "admin-user123@domain.com"

    # Should not raise exception
    LOGIN__USERNAME_validator(None, DummyField())


def test_login_username_validator_invalid():
    class DummyField:
        data = "bad username with spaces!"

    with pytest.raises(ValidationError):
        LOGIN__USERNAME_validator(None, DummyField())


def test_login_form_validation(flask_app):
    with flask_app.test_request_context():
        # Valid form data
        form = IndiAllskyLoginForm(data={
            "USERNAME": "testadmin",
            "PASSWORD": "SecurePassword123!",
            "NEXT": "",
        })
        assert form.validate() is True

        # Missing required password
        form_invalid = IndiAllskyLoginForm(data={
            "USERNAME": "testadmin",
            "PASSWORD": "",
            "NEXT": "",
        })
        assert form_invalid.validate() is False
        assert "PASSWORD" in form_invalid.errors
