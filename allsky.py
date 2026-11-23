#!/usr/bin/env python3

import sys
import os
import multiprocessing
import logging
import traceback
import argparse

from indi_allsky.worker_init import configure_worker_logging


# the flask context cannot created globally
# it will cause problems with DB connections using TLS/SSL


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)


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
    # https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
    start_method = 'forkserver' if 'forkserver' in multiprocessing.get_all_start_methods() else 'fork'
    try:
        multiprocessing.set_start_method(start_method, force=True)
    except RuntimeError:
        pass

    from indi_allsky.allsky import IndiAllSky


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


    # log setup (inherited by forkserver/spawn workers via env var)
    os.environ['INDI_ALLSKY_LOG_TARGET'] = args.log
    configure_worker_logging(args.log)


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
