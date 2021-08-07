#!/usr/bin/env python

import indi_allsky
import logging
import logging.handlers
import argparse
import multiprocessing


logger = multiprocessing.get_logger()

LOG_FORMATTER = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() #%(lineno)d: %(message)s')

#LOG_HANDLER_STREAM = logging.StreamHandler()
#LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER)
#logger.addHandler(LOG_HANDLER_STREAM)

#LOG_HANDLER_FILE = logging.handlers.RotatingFileHandler('./log/indi-allsky.log', maxBytes=10485760, backupCount=5)
#LOG_HANDLER_FILE.setFormatter(LOG_FORMATTER)
#logger.addHandler(LOG_HANDLER_FILE)

LOG_HANDLER_SYSLOG = logging.handlers.SysLogHandler(address='/dev/log', facility='local6')
LOG_HANDLER_SYSLOG.setFormatter(LOG_FORMATTER)
logger.addHandler(LOG_HANDLER_SYSLOG)

logger.setLevel(logging.INFO)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=('run', 'darks', 'generateDayTimelapse', 'generateNightTimelapse', 'generateAllTimelapse', 'expireImages'),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        required=True,
    )
    argparser.add_argument(
        '--timespec',
        '-t',
        help='time spec',
        type=str,
    )

    args = argparser.parse_args()


    args_list = list()

    if args.timespec:
        args_list.append(args.timespec)


    ia = indi_allsky.IndiAllSky(args.config)

    action_func = getattr(ia, args.action)
    action_func(*args_list)


# vim let=g:syntastic_python_flake8_args='--ignore="E203,E303,E501,E265,E266,E201,E202,W391"'
# vim: set tabstop=4 shiftwidth=4 expandtab
