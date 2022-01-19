# WSGI file for mod_wsgi in apache
import logging

from indi_allsky.flask import create_app
application = create_app()

gunicorn_logger = logging.getLogger('gunicorn.error')
application.logger.handlers = gunicorn_logger.handlers
application.logger.setLevel(gunicorn_logger.level)
