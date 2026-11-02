import sys
import types
from unittest.mock import MagicMock, patch
from importlib.machinery import ModuleSpec

class MockModule(types.ModuleType):
    def __init__(self, name):
        super().__init__(name)
        self.__path__ = []

    def __getattr__(self, name):
        val = MagicMock()
        setattr(self, name, val)
        return val

class MockImporter:
    mock_prefixes = (
        'astroalign',
        'astropy',
        'scipy',
        'skimage',
        'ccdproc',
        'ephem',
        'skyfield',
        'pyindi_client',
        'is_safe_url',
        'authlib',
        'pycurl',
    )

    def find_spec(self, fullname, path, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in self.mock_prefixes):
            return ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        mod = MockModule(spec.name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass

sys.meta_path.insert(0, MockImporter())

import os
import time
import pytest
from pathlib import Path
from flask import Flask
from flask_login import LoginManager

template_config = Path(__file__).resolve().parents[2] / 'flask.json_template'
os.environ['INDI_ALLSKY_FLASK_CONFIG'] = str(template_config)

from indi_allsky.flask.auth_views import OIDCBackchannelLogoutView


class DummyInvalidKeyIdError(Exception):
    pass


class DummyOAuthApp:
    def __init__(self, issuer="https://auth.example.com", client_id="test-client-id", jwks=None):
        self.issuer = issuer
        self.client_id = client_id
        self._jwks = jwks or {"keys": []}

    def load_server_metadata(self):
        return {"issuer": self.issuer, "jwks_uri": f"{self.issuer}/protocol/openid-connect/certs"}

    def fetch_jwk_set(self, force=False):
        return self._jwks


@pytest.fixture
def mock_app():
    app = Flask('test_oidc_app')
    app.config['SECRET_KEY'] = 'test-secret-key-123'
    app.config['OIDC_ENABLE'] = True
    app.config['OIDC_CLIENT_ID'] = 'test-client-id'
    app.config['WTF_CSRF_ENABLED'] = False
    return app


def _mock_joserfc(claims):
    mock_joserfc = MagicMock()
    mock_jwt = MagicMock()
    mock_decoded = MagicMock()
    mock_decoded.claims = claims
    mock_jwt.decode.return_value = mock_decoded
    mock_joserfc.jwt = mock_jwt
    mock_jwk = MagicMock()
    mock_joserfc.jwk = mock_jwk
    mock_errors = MagicMock()
    mock_errors.InvalidKeyIdError = DummyInvalidKeyIdError
    mock_joserfc.errors = mock_errors

    return patch.dict('sys.modules', {
        'joserfc': mock_joserfc,
        'joserfc.jwt': mock_jwt,
        'joserfc.jwk': mock_jwk,
        'joserfc.errors': mock_errors,
    })


def test_validate_logout_token_success(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "user_sub_123",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "jti": "jwt-id-999",
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        "sid": "session_sid_456",
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                validated_claims = view._validate_logout_token("dummy.jwt.token")

                assert validated_claims["sub"] == "user_sub_123"
                assert validated_claims["sid"] == "session_sid_456"
                assert validated_claims["iss"] == "https://auth.example.com"


def test_validate_logout_token_invalid_issuer(mock_app):
    claims = {
        "iss": "https://wrong-issuer.com",
        "sub": "user_sub_123",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
    }
    dummy_oauth = DummyOAuthApp(issuer="https://auth.example.com")

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                with pytest.raises(ValueError, match="Issuer mismatch"):
                    view._validate_logout_token("dummy.jwt.token")


def test_validate_logout_token_invalid_audience(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "user_sub_123",
        "aud": "other-client",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                with pytest.raises(ValueError, match="Audience mismatch"):
                    view._validate_logout_token("dummy.jwt.token")


def test_validate_logout_token_contains_nonce_forbidden(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "user_sub_123",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        "nonce": "forbidden-nonce-value",
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                with pytest.raises(ValueError, match="must not contain a nonce claim"):
                    view._validate_logout_token("dummy.jwt.token")


def test_validate_logout_token_missing_event(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "user_sub_123",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {},
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                with pytest.raises(ValueError, match="missing 'http://schemas.openid.net/event/backchannel-logout'"):
                    view._validate_logout_token("dummy.jwt.token")


def test_validate_logout_token_missing_sub_and_sid(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            with _mock_joserfc(claims):
                view = OIDCBackchannelLogoutView()
                with pytest.raises(ValueError, match="must contain either 'sub' or 'sid'"):
                    view._validate_logout_token("dummy.jwt.token")


def test_validate_logout_token_authlib_fallback(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "user_fallback_123",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        "sid": "session_fallback_456",
    }
    dummy_oauth = DummyOAuthApp()

    with mock_app.test_request_context():
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth

            mock_authlib_jwt = MagicMock()
            mock_authlib_jwt.decode.return_value = claims

            # Ensure joserfc is absent so ImportError triggers fallback to authlib.jose
            with patch.dict('sys.modules', {'joserfc': None, 'joserfc.jwt': None, 'authlib.jose': MagicMock(jwt=mock_authlib_jwt)}):
                view = OIDCBackchannelLogoutView()
                validated_claims = view._validate_logout_token("dummy.jwt.token")

                assert validated_claims["sub"] == "user_fallback_123"
                assert validated_claims["sid"] == "session_fallback_456"


def test_backchannel_logout_dispatch_missing_token(mock_app):
    with mock_app.test_request_context(method='POST', data={}):
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = DummyOAuthApp()
            view = OIDCBackchannelLogoutView()
            response = view.dispatch_request()
            assert response.status_code == 400
            assert response.headers.get('Cache-Control') == 'no-store'


def test_backchannel_logout_dispatch_success_revocation(mock_app):
    claims = {
        "iss": "https://auth.example.com",
        "sub": "target_user_sub",
        "sid": "target_session_sid",
        "aud": "test-client-id",
        "iat": int(time.time()),
        "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
    }
    dummy_oauth = DummyOAuthApp()

    mock_user = MagicMock()
    mock_user.data = {
        "idp": "oidc",
        "oidc_sub": "target_user_sub",
        "oidc_sid": "target_session_sid",
    }
    mock_user.username = "allsky_observer"

    with mock_app.test_request_context(method='POST', data={'logout_token': "valid.jwt.token"}):
        with patch('indi_allsky.flask.auth_views.oauth') as mock_oauth:
            mock_oauth.oidc = dummy_oauth
            with patch.object(OIDCBackchannelLogoutView, '_validate_logout_token', return_value=claims):
                with patch('indi_allsky.flask.auth_views.IndiAllSkyDbUserTable') as mock_user_table:
                    mock_user_table.query.all.return_value = [mock_user]
                    with patch('indi_allsky.flask.auth_views.db.session.commit') as mock_commit:
                        view = OIDCBackchannelLogoutView()
                        response = view.dispatch_request()

                        assert response.status_code == 200
                        assert response.headers.get('Cache-Control') == 'no-store'
                        assert response.headers.get('Pragma') == 'no-cache'
                        mock_commit.assert_called_once()

                        assert "oidc_logged_out_at" in mock_user.data
                        assert "target_session_sid" in mock_user.data.get("oidc_revoked_sids", {})


def test_check_oidc_session_prevents_5_minute_logout(mock_app):
    """Verify that OIDC users do not get prematurely logged out after 5 minutes."""
    login_manager = LoginManager()
    login_manager.init_app(mock_app)

    def check_session(curr_user, sess, req_path):
        if not curr_user.is_authenticated:
            return None
        if '/static/' in req_path:
            return None

        user_data = dict(curr_user.data) if curr_user.data else {}
        if user_data.get('idp') == 'oidc':
            session_sid = sess.get('oidc_sid')
            session_login_time = sess.get('oidc_login_time', 0)
            user_logged_out_at = user_data.get('oidc_logged_out_at', 0)
            revoked_sids = user_data.get('oidc_revoked_sids', {})

            is_revoked = False
            if session_sid and session_sid in revoked_sids:
                is_revoked = True
            elif user_logged_out_at and session_login_time <= user_logged_out_at:
                is_revoked = True

            if is_revoked:
                return "LOGOUT"
        return "PROCEED"

    # 1. Normal active user after 10 minutes (600s) - must PROCEED
    active_user = MagicMock(is_authenticated=True)
    active_user.data = {"idp": "oidc", "oidc_sub": "sub1", "oidc_sid": "sid1"}
    active_sess = {"oidc_login_time": 1000, "oidc_sid": "sid1"}
    assert check_session(active_user, active_sess, "/indi-allsky/") == "PROCEED"

    # 2. User with revoked session ID via backchannel logout - must LOGOUT
    revoked_sid_user = MagicMock(is_authenticated=True)
    revoked_sid_user.data = {
        "idp": "oidc",
        "oidc_sub": "sub1",
        "oidc_revoked_sids": {"sid1": 1500},
    }
    revoked_sess = {"oidc_login_time": 1000, "oidc_sid": "sid1"}
    assert check_session(revoked_sid_user, revoked_sess, "/indi-allsky/") == "LOGOUT"

    # 3. User with global sub revocation via backchannel logout - must LOGOUT
    revoked_sub_user = MagicMock(is_authenticated=True)
    revoked_sub_user.data = {
        "idp": "oidc",
        "oidc_sub": "sub1",
        "oidc_logged_out_at": 1500,
    }
    assert check_session(revoked_sub_user, active_sess, "/indi-allsky/") == "LOGOUT"

    # 4. User logged in locally (idp != oidc) - must PROCEED
    local_user = MagicMock(is_authenticated=True)
    local_user.data = {"idp": "local"}
    assert check_session(local_user, {}, "/indi-allsky/") == "PROCEED"
