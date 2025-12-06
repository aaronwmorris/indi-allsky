#!/usr/bin/env python3

import sys
import locale
import logging
import logging.handlers
import traceback
import argparse


from indi_allsky.allsky import IndiAllSky


# the flask context cannot created globally
# it will cause problems with DB connections using TLS/SSL


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s-%(process)d/%(threadName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

LOG_FORMATTER_SYSLOG = logging.Formatter('[%(levelname)s] %(processName)s-%(process)d/%(threadName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_SYSLOG = logging.handlers.SysLogHandler(address='/dev/log', facility='local6')
LOG_HANDLER_SYSLOG.setFormatter(LOG_FORMATTER_SYSLOG)


def unhandled_exception(exc_type, exc_value, exc_traceback):
    # Do not print exception when user cancels the program
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("An uncaught exception occurred:")
    logger.error("Type: %s", exc_type)
    logger.error("Value: %s", exc_value)

    if exc_traceback:
        format_exception = traceback.format_tb(exc_traceback)
        for line in format_exception:
            logger.error(repr(line))


#log unhandled exceptions
sys.excepthook = unhandled_exception


if __name__ == "__main__":
    # should be inherited by all of the sub-processes
    locale.setlocale(locale.LC_ALL, '')

    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=(
            'run',
            'dbImportImages',
        ),
    )
    argparser.add_argument(
        '--cameraId',
        '-C',
        help='camera id (0 == auto)',
        type=int,
        default=0,
    )
    argparser.add_argument(
        '--log',
        '-l',
        help='log output',
        choices=('syslog', 'stderr'),
        default='stderr',
    )
    argparser.add_argument(
        '--pid',
        '-P',
        help='pid file',
        type=str,
        default='/var/lib/indi-allsky/indi-allsky.pid',
    )

    args = argparser.parse_args()


    # log setup
    if args.log == 'syslog':
        logger.addHandler(LOG_HANDLER_SYSLOG)
    elif args.log == 'stderr':
        logger.addHandler(LOG_HANDLER_STREAM)
    else:
        raise Exception('Invalid log output')


    args_list = list()
    kwargs_dict = dict()

    if args.cameraId:
        kwargs_dict['camera_id'] = args.cameraId


    ia = IndiAllSky()
    ia.pid_file = args.pid

    action_func = getattr(ia, args.action)
    action_func(*args_list, **kwargs_dict)


# vim let=g:syntastic_python_flake8_args='--ignore="E203,E303,E501,E265,E266,E201,E202,W391"'
# vim: set tabstop=4 shiftwidth=4 expandtab
