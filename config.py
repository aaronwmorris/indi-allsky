#!/usr/bin/env python3

import locale
import argparse
import logging

from indi_allsky.config import IndiAllSkyConfigUtil


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.addHandler(LOG_HANDLER_STREAM)



if __name__ == "__main__":
    # should be inherited by all of the sub-processes
    locale.setlocale(locale.LC_ALL, '')

    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='configuration management actions',
        choices=(
            'bootstrap',        # load initial config
            'list',             # list configs
            'load',             # load exported config
            'dump',             # export config to STDOUT
            'dumpfile',         # export config to file
            'update_level',     # update config functional level
            'edit',             # edit config in cli
            'revert',           # revert to an older config --id
            'user_count',       # return count of active users to STDOUT
            'delete',           # deletes config by --id
            'flush',            # deletes all configs
        ),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r', encoding='utf-8'),
    )
    argparser.add_argument(
        '--outfile',
        '-o',
        help='output file',
        type=str,
        default='',
    )
    argparser.add_argument(
        '--id',
        '-i',
        help='config id (revert/dump)',
        type=int,
    )
    argparser.add_argument(
        '--force',
        help='force changes',
        dest='force',
        action='store_true',
    )
    argparser.set_defaults(force=False)

    args = argparser.parse_args()


    iacu = IndiAllSkyConfigUtil()
    action_func = getattr(iacu, args.action)
    action_func(
        config=args.config,
        outfile=args.outfile,
        config_id=args.id,
        force=args.force,
    )

