from functools import wraps

from flask import current_app as app

from flask_login import current_user


def login_optional(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if app.config.get("LOGIN_DISABLED"):
            pass
        elif not app.config.get('INDI_ALLSKY_AUTH_ALL_VIEWS'):
            # allow some views to be unauthenticated
            pass
        elif not current_user.is_authenticated:
            return app.login_manager.unauthorized()

        # flask 1.x compatibility
        # current_app.ensure_sync is only available in Flask >= 2.0
        if callable(getattr(app, "ensure_sync", None)):
            return app.ensure_sync(func)(*args, **kwargs)
        return func(*args, **kwargs)

    return decorated_view


def login_optional_media(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if app.config.get("LOGIN_DISABLED"):
            pass
        elif not app.config.get('INDI_ALLSKY_AUTH_ALL_VIEWS') and not app.config.get('INDI_ALLSKY_AUTH_MEDIA_VIEWS'):
            # allow some views to be unauthenticated
            pass
        elif not current_user.is_authenticated:
            return app.login_manager.unauthorized()

        # flask 1.x compatibility
        # current_app.ensure_sync is only available in Flask >= 2.0
        if callable(getattr(app, "ensure_sync", None)):
            return app.ensure_sync(func)(*args, **kwargs)
        return func(*args, **kwargs)

    return decorated_view



def encrypt_json_secret(obj, password_key):
    import json
    from cryptography.fernet import Fernet
    f_key = Fernet(password_key.encode())
    return f_key.encrypt(json.dumps(obj).encode('utf-8')).decode('utf-8')


def decrypt_json_secret(token_val, password_key):
    import json
    from cryptography.fernet import Fernet
    if isinstance(token_val, dict):
        return token_val
    f_key = Fernet(password_key.encode())
    return json.loads(f_key.decrypt(token_val.encode('utf-8')).decode('utf-8'))


def is_valid_ws_origin(req):
    """Validate browser WebSocket Origin header against request.host when present."""
    from urllib.parse import urlsplit
    origin = req.headers.get('Origin')
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.netloc == req.host
