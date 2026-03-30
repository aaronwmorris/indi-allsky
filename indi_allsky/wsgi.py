# WSGI file for mod_wsgi in apache/gunicorn
#
# This file is monitored for changes via inotify
# Updates should restart gunicorn automatically
#
# Version 00023
#
import logging

from indi_allsky.flask import create_app
application = create_app()


class _RootRedirect:
    """WSGI middleware: redirect / to /indi-allsky/ when no reverse proxy."""
    def __init__(self, app):
        self._app = app
    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO", "/") == "/":
            start_response("302 Found", [("Location", "/indi-allsky/")])
            return [b""]
        return self._app(environ, start_response)


gunicorn_logger = logging.getLogger('gunicorn.error')
application.logger.handlers = gunicorn_logger.handlers
application.logger.setLevel(gunicorn_logger.level)

application = _RootRedirect(application)
