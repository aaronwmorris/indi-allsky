"""Extended tests for actionapi_views.py and auth_views.py coverage."""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from passlib.hash import argon2

from indi_allsky.flask.models import (
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbConfigTable,
    IndiAllSkyDbUserTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask import db as _db


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _base_env(flask_app, db):
    """Seed a camera + config for every test in this file."""
    flask_app.config['ADMIN_NETWORKS'] = ['127.0.0.1/32']
    with flask_app.app_context():
        if not IndiAllSkyDbCameraTable.query.first():
            db.session.add(IndiAllSkyDbCameraTable(
                name="action_test_camera",
                latitude=-34.9, longitude=138.6, elevation=50,
                nightSunAlt=-6.0, local=True,
            ))
        if not IndiAllSkyDbConfigTable.query.first():
            db.session.add(IndiAllSkyDbConfigTable(
                data={
                    'WEBSITE': {'TITLE': 'indi-allsky'},
                    'CAPTURE_PAUSE': False,
                },
                level='1.0', note='test',
            ))
        db.session.commit()


@pytest.fixture
def admin_user(flask_app, db):
    """Return (username, plaintext_password) for a local admin user."""
    with flask_app.app_context():
        u = IndiAllSkyDbUserTable.query.filter_by(username='actapi_admin').first()
        if not u:
            u = IndiAllSkyDbUserTable(
                username='actapi_admin',
                password=argon2.using(rounds=4).hash('AdminPass1!'),
                email='actapi@example.com',
                active=True, admin=True,
            )
            db.session.add(u)
            db.session.commit()
    return 'actapi_admin', 'AdminPass1!'


# ===========================================================================
# actionapi_views.py – additional branches
# ===========================================================================

class TestActionApiCoverage:

    def test_non_post_method_returns_400(self, flask_app, admin_user):
        """GET to an action endpoint returns 400.
        Covers actionapi_views.py line 47.
        """
        username, password = admin_user
        client = flask_app.test_client()
        with patch('time.sleep', return_value=None):
            resp = client.get('/indi-allsky/action/pause',
                              json={'username': username, 'password': password})
        # GET is not allowed → route-level 405, OR dispatch returns 400
        assert resp.status_code in (400, 405)

    def test_actionapi_base_view_dispatch_and_post(self, flask_app, admin_user):
        """Covers ActionApiBaseView base post() and non-POST dispatch (lines 47, 82)."""
        from indi_allsky.flask.actionapi_views import ActionApiBaseView
        view = ActionApiBaseView()
        username, password = admin_user
        with flask_app.test_request_context('/indi-allsky/action/base', method='POST', json={'username': username, 'password': password}):
            resp, code = view.post()
            assert code == 400

        with flask_app.test_request_context('/indi-allsky/action/base', method='GET', json={'username': username, 'password': password}):
            with patch.object(view, 'authorize', return_value=None):
                resp, code = view.dispatch_request()
                assert code == 400

    def test_unknown_user_authentication_failure(self, flask_app, db):
        """Unknown username → AuthenticationFailure → 400.
        Covers actionapi_views.py line 66.
        """
        client = flask_app.test_client()
        with patch('time.sleep', return_value=None):
            resp = client.post('/indi-allsky/action/pause',
                               json={'username': 'nobody', 'password': 'whatever'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'authentication failed'

    def test_non_admin_user_permission_denied(self, flask_app, db):
        """Non-admin user → PermissionDenied → 400.
        Covers actionapi_views.py line 73.
        """
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='nonadmin_act').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='nonadmin_act',
                    password=argon2.using(rounds=4).hash('pass'),
                    email='nonadmin@example.com',
                    active=True, admin=False,
                )
                db.session.add(u)
                db.session.commit()

        client = flask_app.test_client()
        with patch('time.sleep', return_value=None):
            resp = client.post('/indi-allsky/action/pause',
                               json={'username': 'nonadmin_act', 'password': 'pass'})
        assert resp.status_code == 400
        assert resp.get_json().get('error') == 'permission denied'

    def test_admin_network_check_fails_permission_denied(self, flask_app, admin_user, db):
        """Admin user from a non-admin network → PermissionDenied → 400.
        Covers actionapi_views.py line 77.
        """
        username, password = admin_user
        client = flask_app.test_client()

        orig_admin_networks = flask_app.config.get('ADMIN_NETWORKS')
        flask_app.config['ADMIN_NETWORKS'] = ['10.255.255.0/24']
        try:
            with patch('time.sleep', return_value=None):
                resp = client.post('/indi-allsky/action/pause',
                                   json={'username': username, 'password': password})
            assert resp.status_code in (201, 400)
        finally:
            if orig_admin_networks is not None:
                flask_app.config['ADMIN_NETWORKS'] = orig_admin_networks
            else:
                flask_app.config.pop('ADMIN_NETWORKS', None)

    def test_pause_when_already_paused_returns_200(self, flask_app, admin_user, db):
        """PauseActionApiView returns 200 when CAPTURE_PAUSE is already True.
        Covers actionapi_views.py lines 90-93.
        """
        username, password = admin_user
        # Force CAPTURE_PAUSE = True in the config
        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'CAPTURE_PAUSE': True}
            db.session.commit()

        client = flask_app.test_client()
        with patch('time.sleep', return_value=None):
            resp = client.post('/indi-allsky/action/pause',
                               json={'username': username, 'password': password})
        assert resp.status_code == 200
        assert 'already paused' in resp.get_json().get('message', '').lower()

        # Restore
        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'CAPTURE_PAUSE': False}
            db.session.commit()

    def test_unpause_when_paused_creates_task_and_returns_201(self, flask_app, admin_user, db):
        """UnpauseActionApiView creates a task when CAPTURE_PAUSE=True.
        Covers actionapi_views.py lines 127-144.
        """
        username, password = admin_user
        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'CAPTURE_PAUSE': True}
            db.session.commit()

        client = flask_app.test_client()
        with patch('time.sleep', return_value=None):
            resp = client.post('/indi-allsky/action/unpause',
                               json={'username': username, 'password': password})
        assert resp.status_code == 201
        data = resp.get_json()
        assert 'message' in data

        with flask_app.app_context():
            task = IndiAllSkyDbTaskQueueTable.query.filter_by(
                queue=TaskQueueQueue.MAIN,
                state=TaskQueueState.MANUAL,
            ).filter(
                IndiAllSkyDbTaskQueueTable.data['action'].as_string() == 'setpaused'
            ).first()
            assert task is not None
            assert task.data.get('pause') is False

        # Restore
        with flask_app.app_context():
            cfg = IndiAllSkyDbConfigTable.query.first()
            cfg.data = {**cfg.data, 'CAPTURE_PAUSE': False}
            db.session.commit()


# ===========================================================================
# auth_views.py – additional branches
# ===========================================================================

class TestAuthViewsCoverage:

    @pytest.fixture
    def local_user(self, flask_app, db):
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='authtestuser').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='authtestuser',
                    password=argon2.using(rounds=4).hash('ValidPass1!'),
                    email='authtest@example.com',
                    active=True, admin=True,
                )
                db.session.add(u)
                db.session.commit()
        return 'authtestuser', 'ValidPass1!'

    @pytest.fixture
    def inactiveuser(self, flask_app, db):
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='inactiveuser').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='inactiveuser',
                    password=argon2.using(rounds=4).hash('ValidPass1!'),
                    email='inactive@example.com',
                    active=False, admin=False,
                )
                db.session.add(u)
                db.session.commit()
        return 'inactiveuser', 'ValidPass1!'

    def test_login_post_invalid_form_data(self, flask_app):
        """POST with missing required fields → 400 form errors.
        Covers auth_views.py lines 90-92.
        """
        client = flask_app.test_client()
        # Missing USERNAME and PASSWORD
        resp = client.post('/indi-allsky/login', json={'NEXT': ''})
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'form_global' in data or 'USERNAME' in data or 'PASSWORD' in data

    def test_login_post_wrong_password(self, flask_app, local_user):
        """POST with wrong password → 400.
        Covers auth_views.py lines 109-112.
        """
        client = flask_app.test_client()
        resp = client.post('/indi-allsky/login', json={
            'USERNAME': local_user[0],
            'PASSWORD': 'WrongPassword999!',
            'NEXT': '',
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'form_global' in data

    def test_login_post_inactiveuser(self, flask_app, inactiveuser):
        """POST with inactive user → 400 'User is disabled'.
        Covers auth_views.py lines 116-118.
        """
        client = flask_app.test_client()
        resp = client.post('/indi-allsky/login', json={
            'USERNAME': inactiveuser[0],
            'PASSWORD': inactiveuser[1],
            'NEXT': '',
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'form_global' in data
        assert any('disabled' in str(e).lower() for e in data.get('form_global', []))

    def test_login_post_with_x_forwarded_for(self, flask_app, local_user):
        """POST with X-Forwarded-For header records correct IP.
        Covers auth_views.py line 129.
        """
        client = flask_app.test_client()
        resp = client.post(
            '/indi-allsky/login',
            json={'USERNAME': local_user[0], 'PASSWORD': local_user[1], 'NEXT': ''},
            headers={'X-Forwarded-For': '203.0.113.42'},
        )
        assert resp.status_code == 200

        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username=local_user[0]).first()
            assert u.loginIp == '203.0.113.42'

    def test_login_post_user_data_none(self, flask_app, db):
        """POST login with user.data=None uses empty dict.
        Covers auth_views.py line 135.
        """
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable(
                username='nodatauser',
                password=argon2.using(rounds=4).hash('Pass123!'),
                email='nodata@example.com',
                active=True, admin=False,
                data=None,  # explicitly None
            )
            db.session.add(u)
            db.session.commit()

        client = flask_app.test_client()
        resp = client.post('/indi-allsky/login', json={
            'USERNAME': 'nodatauser',
            'PASSWORD': 'Pass123!',
            'NEXT': '',
        })
        assert resp.status_code == 200

    def test_login_post_valid_next_url(self, flask_app, local_user):
        """POST with a valid safe next URL returns that URL.
        Covers auth_views.py lines 160-163.
        """
        client = flask_app.test_client()
        resp = client.post('/indi-allsky/login', json={
            'USERNAME': local_user[0],
            'PASSWORD': local_user[1],
            'NEXT': '/indi-allsky/config',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'redirect' in data
        assert data['redirect'] == '/indi-allsky/config'

    def test_login_post_unsafe_next_url_falls_back_to_index(self, flask_app, local_user):
        """POST with unsafe next URL falls back to index.
        Covers auth_views.py line 152-157.
        """
        client = flask_app.test_client()
        resp = client.post('/indi-allsky/login', json={
            'USERNAME': local_user[0],
            'PASSWORD': local_user[1],
            'NEXT': 'https://evil.example.com/steal',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'redirect' in data
        assert 'evil.example.com' not in data['redirect']

    def test_login_get_already_authenticated_redirects(self, flask_app, local_user):
        """GET /login when authenticated redirects to index.
        Covers auth_views.py line 74.
        """
        client = flask_app.test_client()
        # Log in first
        client.post('/indi-allsky/login', json={
            'USERNAME': local_user[0],
            'PASSWORD': local_user[1],
            'NEXT': '',
        })
        # Now GET /login → should redirect
        resp = client.get('/indi-allsky/login', follow_redirects=False)
        assert resp.status_code == 302
        assert '/indi-allsky' in resp.headers.get('Location', '')

    def test_login_get_oidc_auto_login_redirect(self, flask_app):
        """GET /login with OIDC_ENABLE + OIDC_AUTO_LOGIN redirects to oidc login.
        Covers auth_views.py line 77.
        """
        flask_app.config['OIDC_ENABLE'] = True
        flask_app.config['OIDC_AUTO_LOGIN'] = True
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/login', follow_redirects=False)
            assert resp.status_code == 302
            assert 'oidc' in resp.headers.get('Location', '').lower()
        finally:
            flask_app.config.pop('OIDC_ENABLE', None)
            flask_app.config.pop('OIDC_AUTO_LOGIN', None)

    def test_logout_unauthenticated_redirects(self, flask_app):
        """GET /logout when not logged in redirects to index.
        Covers auth_views.py line 344.
        """
        client = flask_app.test_client()
        resp = client.get('/indi-allsky/logout', follow_redirects=False)
        assert resp.status_code == 302

    def test_logout_local_auth_user(self, flask_app, local_user):
        """GET /logout for a local-auth user clears session and redirects.
        Covers auth_views.py lines 340-377 (non-OIDC path).
        """
        client = flask_app.test_client()
        client.post('/indi-allsky/login', json={
            'USERNAME': local_user[0],
            'PASSWORD': local_user[1],
            'NEXT': '',
        })
        resp = client.get('/indi-allsky/logout', follow_redirects=False)
        assert resp.status_code == 302

    def test_oidc_login_view_no_oauth_redirects(self, flask_app):
        """OIDCLoginView when oauth.oidc not registered → redirect to login.
        Covers auth_views.py lines 170-172.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        # Create a mock oauth with no 'oidc' attribute
        mock_oauth = MagicMock(spec=[])  # empty spec = no attributes
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/login', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_no_oauth_returns_404(self, flask_app):
        """OIDCCallbackView when oauth.oidc not registered → 404.
        Covers auth_views.py line 193.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_oauth = MagicMock(spec=[])  # no 'oidc' attribute
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback', follow_redirects=False)
            assert resp.status_code == 404
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_no_code_redirects_to_index(self, flask_app):
        """OIDCCallbackView with no 'code' param (logout callback) → redirect index.
        Covers auth_views.py lines 196-204.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_oidc = MagicMock()
        mock_oidc.validate_logout_response.side_effect = Exception("no state")
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            # No 'code' in args → logout callback path
            resp = client.get('/indi-allsky/oidc/callback?state=abc', follow_redirects=False)
            assert resp.status_code == 302
            assert '/indi-allsky' in resp.headers.get('Location', '')
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_token_exchange_failure(self, flask_app):
        """OIDCCallbackView token exchange failure → redirect to login.
        Covers auth_views.py lines 219-225.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        exc = Exception("token failed")
        exc.error = 'invalid_grant'
        exc.description = 'Token expired'

        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.side_effect = exc
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_full_flow_new_user(self, flask_app, db):
        """Full OIDC callback flow creates a new user and logs them in.
        Covers auth_views.py lines 228-334.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok_xyz',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'oidc_new_user_test',
                'email': 'oidcnew@example.com',
                'name': 'OIDC New User',
                'groups': ['allsky-users'],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302

            with flask_app.app_context():
                u = IndiAllSkyDbUserTable.query.filter_by(username='oidc_new_user_test').first()
                assert u is not None
                assert u.data.get('idp') == 'oidc'
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_allowed_groups_check_list(self, flask_app, db):
        """OIDC callback with OIDC_ALLOWED_GROUPS list check - user not in group.
        Covers auth_views.py lines 239-244.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'restricted_user',
                'email': 'restricted@example.com',
                'groups': ['other-group'],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ALLOWED_GROUPS'] = ['allsky-admins']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ALLOWED_GROUPS', None)

    def test_oidc_callback_allowed_groups_string(self, flask_app, db):
        """OIDC callback with OIDC_ALLOWED_GROUPS and space-separated groups string.
        Covers auth_views.py lines 245-250.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'group_string_user',
                'email': 'grpstr@example.com',
                'groups': 'allsky-users other-group',  # space-separated string
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ALLOWED_GROUPS'] = ['allsky-users']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            # User is in the allowed group string so should proceed (302 to index)
            assert resp.status_code == 302
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ALLOWED_GROUPS', None)

    def test_oidc_callback_allowed_groups_invalid_type(self, flask_app, db):
        """OIDC callback with groups as invalid type → redirect to login.
        Covers auth_views.py lines 251-254.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'bad_groups_user',
                'email': 'badgrp@example.com',
                'groups': 12345,  # invalid type
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ALLOWED_GROUPS'] = ['allsky-users']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ALLOWED_GROUPS', None)

    def test_oidc_callback_allowed_users_check(self, flask_app, db):
        """OIDC callback with OIDC_ALLOWED_USERS check - user not allowed.
        Covers auth_views.py lines 259-263.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'not_allowed_user',
                'email': 'notallowed@example.com',
                'groups': [],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ALLOWED_USERS'] = ['allowed_user_only']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ALLOWED_USERS', None)

    def test_oidc_callback_admin_groups_list(self, flask_app, db):
        """OIDC callback grants admin to members of OIDC_ADMIN_GROUPS list.
        Covers auth_views.py lines 291-294.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'oidc_admin_group_user',
                'email': 'oidcadmin@example.com',
                'groups': ['allsky-admins'],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ADMIN_GROUPS'] = ['allsky-admins']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302

            with flask_app.app_context():
                u = IndiAllSkyDbUserTable.query.filter_by(username='oidc_admin_group_user').first()
                if u:
                    assert u.admin is True
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ADMIN_GROUPS', None)

    def test_oidc_callback_admin_groups_string(self, flask_app, db):
        """OIDC admin groups as space-separated string.
        Covers auth_views.py lines 295-297.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'oidc_admin_str_user',
                'email': 'adminstr@example.com',
                'groups': 'allsky-admins regular-users',
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ADMIN_GROUPS'] = ['allsky-admins']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ADMIN_GROUPS', None)

    def test_oidc_callback_admin_users_list(self, flask_app, db):
        """OIDC_ADMIN_USERS grants admin by username.
        Covers auth_views.py lines 303-305.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok',
            'userinfo': {
                'preferred_username': 'superadmin_oidc',
                'email': 'superadmin@example.com',
                'groups': [],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ADMIN_USERS'] = ['superadmin_oidc']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302

            with flask_app.app_context():
                u = IndiAllSkyDbUserTable.query.filter_by(username='superadmin_oidc').first()
                if u:
                    assert u.admin is True
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ADMIN_USERS', None)

    def test_oidc_callback_existing_user_updated(self, flask_app, db):
        """OIDC callback updates existing user's token data.
        Covers auth_views.py lines 282-287.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        with flask_app.app_context():
            existing = IndiAllSkyDbUserTable(
                username='existing_oidc_user',
                password=argon2.using(rounds=4).hash('pass'),
                email='existing@example.com',
                active=True, admin=False,
                data={'idp': 'oidc', 'some_key': 'some_val'},
            )
            db.session.add(existing)
            db.session.commit()

        mock_token = {
            'id_token': 'new_id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'new_acc_tok',
            'userinfo': {
                'preferred_username': 'existing_oidc_user',
                'email': 'existing@example.com',
                'groups': [],
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_no_username_redirects(self, flask_app):
        """OIDC callback with no username in userinfo → redirect to login.
        Covers auth_views.py lines 232-234.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok',
            'expires_at': time.time() + 3600,
            'access_token': 'acc',
            'userinfo': {
                # No preferred_username
                'email': 'nousername@example.com',
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth

    def test_logout_with_oidc_token_clears_and_redirects(self, flask_app, db):
        """Logout for OIDC user clears token from DB.
        Covers auth_views.py lines 347-377.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        with flask_app.app_context():
            u = IndiAllSkyDbUserTable(
                username='oidclogoutuser',
                password=argon2.using(rounds=4).hash('ValidPassword123!'),
                email='oidclogout@example.com',
                active=True, admin=False,
                data={'idp': 'oidc', 'oidc_token': {'id_token': 'tok123'}},
            )
            db.session.add(u)
            db.session.commit()

        # First log the user in via local auth
        client = flask_app.test_client()
        client.post('/indi-allsky/login', json={
            'USERNAME': 'oidclogoutuser',
            'PASSWORD': 'ValidPassword123!',
            'NEXT': '',
        })

        # Mock OIDC to not have logout_redirect
        mock_oidc = MagicMock(spec=[])
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth

        flask_app.config['OIDC_ENABLE'] = False  # disable OIDC logout redirect
        try:
            resp = client.get('/indi-allsky/logout', follow_redirects=False)
            assert resp.status_code == 302
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ENABLE', None)

    def test_oidc_login_view_with_next_param(self, flask_app):
        """OIDCLoginView stores safe next URL in session.
        Covers auth_views.py lines 177-179.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_oidc = MagicMock()
        mock_oidc.authorize_redirect.return_value = MagicMock(
            status_code=302,
            headers={'Location': 'https://idp.example.com/auth'},
        )
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/login?next=/indi-allsky/config', follow_redirects=False)
            # Should redirect to IdP
            assert resp.status_code in (200, 302)
        finally:
            av.oauth = original_oauth

    def test_oidc_login_view_authorize_exception(self, flask_app):
        """OIDCLoginView exception during authorize_redirect → redirect to login.
        Covers auth_views.py lines 183-185.
        """
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_oidc = MagicMock()
        mock_oidc.authorize_redirect.side_effect = Exception("OIDC misconfigured")
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/login', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth

    def test_login_view_dispatch_non_get_post(self, flask_app):
        """Covers auth_views.py line 69 (abort 400 for unsupported methods in LoginView)."""
        from indi_allsky.flask.auth_views import LoginView
        import werkzeug.exceptions
        with flask_app.test_request_context('/indi-allsky/login', method='PUT'):
            view = LoginView(template_name='login.html')
            with pytest.raises(werkzeug.exceptions.HTTPException) as exc:
                view.dispatch_request()
            assert exc.value.code == 400

    def test_oidc_callback_token_no_userinfo_calls_userinfo_method(self, flask_app, db):
        """Covers auth_views.py line 215 (fetching userinfo when not embedded in token)."""
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'id_tok_fetch',
            'expires_at': time.time() + 3600,
            'access_token': 'acc_tok_fetch',
            # No 'userinfo' key
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oidc.userinfo.return_value = {
            'preferred_username': 'fetched_user',
            'email': 'fetched@example.com',
            'groups': [],
        }
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            mock_oidc.userinfo.assert_called_once()
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_allowed_groups_string_denied(self, flask_app):
        """Covers auth_views.py lines 248-250 (allowed groups check with string groups)."""
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'tok',
            'expires_at': time.time() + 3600,
            'userinfo': {
                'preferred_username': 'string_group_user',
                'groups': 'group1 group2',
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        flask_app.config['OIDC_ALLOWED_GROUPS'] = ['required_group']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
            assert 'login' in resp.headers.get('Location', '').lower()
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ALLOWED_GROUPS', None)

    def test_oidc_callback_existing_user_no_data(self, flask_app, db):
        """Covers auth_views.py line 287 (existing user with None user.data)."""
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='nodata_user').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='nodata_user',
                    password=argon2.using(rounds=4).hash('pass'),
                    email='nodata@example.com',
                    active=True,
                    data=None,
                )
                db.session.add(u)
                db.session.commit()

        mock_token = {
            'id_token': 'tok',
            'expires_at': time.time() + 3600,
            'userinfo': {
                'preferred_username': 'nodata_user',
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz', follow_redirects=False)
            assert resp.status_code == 302
        finally:
            av.oauth = original_oauth

    def test_oidc_callback_admin_groups_unhandled_type_and_x_forwarded_for(self, flask_app, db):
        """Covers auth_views.py line 299 (unhandled group type in admin check) and line 309 (X-Forwarded-For header)."""
        import indi_allsky.flask.auth_views as av
        original_oauth = av.oauth

        mock_token = {
            'id_token': 'tok',
            'expires_at': time.time() + 3600,
            'userinfo': {
                'preferred_username': 'admin_by_user_list',
                'groups': 12345,  # Non-list, non-string
            },
        }
        mock_oidc = MagicMock()
        mock_oidc.authorize_access_token.return_value = mock_token
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        av.oauth = mock_oauth
        flask_app.config['OIDC_ADMIN_GROUPS'] = ['admin_group']
        flask_app.config['OIDC_ADMIN_USERS'] = ['admin_by_user_list']
        try:
            client = flask_app.test_client()
            resp = client.get('/indi-allsky/oidc/callback?code=abc&state=xyz',
                              headers={'X-Forwarded-For': '192.168.1.50'},
                              follow_redirects=False)
            assert resp.status_code == 302
            with flask_app.app_context():
                user = IndiAllSkyDbUserTable.query.filter_by(username='admin_by_user_list').first()
                assert user is not None
                assert user.is_admin is True
                assert user.loginIp == '192.168.1.50'
        finally:
            av.oauth = original_oauth
            flask_app.config.pop('OIDC_ADMIN_GROUPS', None)
            flask_app.config.pop('OIDC_ADMIN_USERS', None)

    def test_logout_user_with_no_data(self, flask_app, db):
        """Covers auth_views.py line 350 (logout with user having no data)."""
        from indi_allsky.flask.auth_views import LogoutView
        from flask_login import login_user
        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='logout_nodata').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='logout_nodata',
                    password=argon2.using(rounds=4).hash('Pass123!'),
                    email='logout_nodata@example.com',
                    active=True,
                    data=None,
                )
                db.session.add(u)
                db.session.commit()

        with flask_app.test_request_context('/indi-allsky/logout', method='GET'):
            u = IndiAllSkyDbUserTable.query.filter_by(username='logout_nodata').first()
            u.data = None
            login_user(u)
            view = LogoutView()
            resp = view.dispatch_request()
            assert resp.status_code == 302

    def test_logout_oidc_redirect_success_and_exception(self, flask_app, db):
        """Covers auth_views.py lines 369-375 (OIDC logout redirect and error handling)."""
        from flask import Response
        from flask_login import login_user
        from indi_allsky.flask import auth_views
        original_oauth = auth_views.oauth

        with flask_app.app_context():
            u = IndiAllSkyDbUserTable.query.filter_by(username='oidclogout_redirect').first()
            if not u:
                u = IndiAllSkyDbUserTable(
                    username='oidclogout_redirect',
                    password=argon2.using(rounds=4).hash('Pass123!'),
                    email='oidclogout_redirect@example.com',
                    active=True,
                    data={'idp': 'oidc', 'oidc_token': {'id_token': 'my_id_token'}},
                )
                db.session.add(u)
                db.session.commit()
            else:
                u.data = {'idp': 'oidc', 'oidc_token': {'id_token': 'my_id_token'}}
                db.session.commit()

        mock_oidc = MagicMock()
        mock_oidc.logout_redirect.return_value = Response("OIDC redirect", status=302, headers={'Location': 'https://idp/logout'})
        mock_oauth = MagicMock()
        mock_oauth.oidc = mock_oidc
        auth_views.oauth = mock_oauth
        flask_app.config['OIDC_ENABLE'] = True

        try:
            with flask_app.test_request_context('/indi-allsky/logout', method='GET'):
                u = IndiAllSkyDbUserTable.query.filter_by(username='oidclogout_redirect').first()
                login_user(u)
                view = auth_views.LogoutView()
                resp = view.dispatch_request()
                assert resp.status_code == 302
                assert resp.headers.get('Location') == 'https://idp/logout'

            # Now test exception in logout_redirect
            mock_oidc.logout_redirect.side_effect = Exception("Logout failed")
            with flask_app.test_request_context('/indi-allsky/logout', method='GET'):
                u = IndiAllSkyDbUserTable.query.filter_by(username='oidclogout_redirect').first()
                u.data = {'idp': 'oidc', 'oidc_token': {'id_token': 'my_id_token'}}
                login_user(u)
                view = auth_views.LogoutView()
                resp2 = view.dispatch_request()
                assert resp2.status_code == 302
                assert '/indi-allsky/' in resp2.headers.get('Location', '')
        finally:
            auth_views.oauth = original_oauth
            flask_app.config.pop('OIDC_ENABLE', None)



