#!/usr/bin/env python

import indi_timelapse

import logging
import argparse

import multiprocessing


logger = multiprocessing.get_logger()
LOG_FORMATTER = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() #%(lineno)d: %(message)s')
LOG_HANDLER = logging.StreamHandler()
LOG_HANDLER.setFormatter(LOG_FORMATTER)
LOG_LEVEL = logging.INFO
logger.addHandler(LOG_HANDLER)
logger.setLevel(LOG_LEVEL)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=('run', 'darks', 'generateDayTimelapse', 'generateNightTimelapse', 'generateAllTimelapse'),
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


    it = indi_timelapse.IndiTimelapse(args.config)

    action_func = getattr(it, args.action)
    action_func(*args_list)


# vim let=g:syntastic_python_flake8_args='--ignore="E203,E303,E501,E265,E266,E201,E202,W391"'
# vim: set tabstop=4 shiftwidth=4 expandtab
