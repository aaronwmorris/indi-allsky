import locale
import logging
import logging.handlers
import os


LOG_FORMATTER_STREAM = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(processName)s-%(process)d/%(threadName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s'
)
LOG_FORMATTER_SYSLOG = logging.Formatter(
    '[%(levelname)s] %(processName)s-%(process)d/%(threadName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s'
)


def configure_worker_logging(log_target=None):
    """Initialize locale and logging handlers for main and forkserver/spawn workers."""
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pass

    target = log_target or os.environ.get('INDI_ALLSKY_LOG_TARGET', 'stderr')
    if target not in ('syslog', 'stderr'):
        raise ValueError('Invalid log output: {0!r}'.format(target))

    logger = logging.getLogger('indi_allsky')
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    if target == 'syslog':
        handler = logging.handlers.SysLogHandler(
            address='/dev/log',
            facility=logging.handlers.SysLogHandler.LOG_LOCAL6,
        )
        handler.setFormatter(LOG_FORMATTER_SYSLOG)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(LOG_FORMATTER_STREAM)

    logger.addHandler(handler)
    return logger
