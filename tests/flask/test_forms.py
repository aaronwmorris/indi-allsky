from indi_allsky.flask.forms import (
    IndiAllskyLoginForm,
    IndiAllskyCameraSelectForm,
)


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


def test_camera_select_form_validation(flask_app):
    with flask_app.test_request_context():
        form = IndiAllskyCameraSelectForm(data={
            "CAMERA": "1",
        })
        # Unpopulated camera choices -> validation fails cleanly
        assert form.validate() is False
