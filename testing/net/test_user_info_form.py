from pathlib import Path
from types import SimpleNamespace
import unittest

from flask import Flask
from passlib.hash import argon2

from indi_allsky.flask.forms import IndiAllskyUserInfoForm


class TestUserInfoForm(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[2]
        cls.app = Flask(__name__)
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['SECRET_KEY'] = 'test'

    def test_user_info_validates_without_idp(self):
        user = SimpleNamespace(password=argon2.hash('oldpassword1'))
        data = {
            'USERNAME': 'u',
            'NAME': 'New Name',
            'EMAIL': 'x@y.z',
            'ADMIN': True,
            'CURRENT_PASSWORD': 'oldpassword1',
            'NEW_PASSWORD': 'newpassword1',
            'NEW_PASSWORD2': 'newpassword1',
        }

        with self.app.app_context():
            form = IndiAllskyUserInfoForm(data=data)
            self.assertTrue(form.validate(user), msg=form.errors)

    def test_mismatched_password_still_rejected(self):
        user = SimpleNamespace(password=argon2.hash('oldpassword1'))
        data = {
            'USERNAME': 'u',
            'NAME': 'New Name',
            'EMAIL': 'x@y.z',
            'ADMIN': True,
            'CURRENT_PASSWORD': 'oldpassword1',
            'NEW_PASSWORD': 'newpassword1',
            'NEW_PASSWORD2': 'different123',
        }

        with self.app.app_context():
            form = IndiAllskyUserInfoForm(data=data)
            self.assertFalse(form.validate(user))
            self.assertIn('NEW_PASSWORD2', form.errors)
            self.assertNotIn('IDP', form.errors)

    def test_user_template_renders_form_global_errors(self):
        user_html = (self.project_root / 'indi_allsky' / 'flask' / 'templates' / 'user.html').read_text(encoding='utf-8')
        self.assertNotIn("if (key === 'form_global' || !fields[key]) return;", user_html)
        self.assertIn('failureMessage.text(errors[key][0]).show()', user_html)


if __name__ == '__main__':
    unittest.main()
