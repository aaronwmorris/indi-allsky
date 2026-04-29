# WSGI file for mod_wsgi in apache/gunicorn
#
# This file is monitored for changes via inotify
# Updates should restart gunicorn automatically
#
# Version 20260401.0
#
import logging

from indi_allsky.flask import create_app
application = create_app()

gunicorn_logger = logging.getLogger('gunicorn.error')
application.logger.handlers = gunicorn_logger.handlers
application.logger.setLevel(gunicorn_logger.level)


# Attach a syslog handler so 'indi_allsky' logger messages appear in webapp log
LOG_FORMATTER_SYSLOG = logging.Formatter('[%(levelname)s] %(processName)s-%(process)d %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_SYSLOG = logging.handlers.SysLogHandler(address='/dev/log', facility=logging.handlers.SysLogHandler.LOG_LOCAL7)
LOG_HANDLER_SYSLOG.setFormatter(LOG_FORMATTER_SYSLOG)

indi_allsky_logger = logging.getLogger('indi_allsky')
indi_allsky_logger.setLevel(logging.INFO)
indi_allsky_logger.addHandler(LOG_HANDLER_SYSLOG)
