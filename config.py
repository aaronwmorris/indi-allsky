#!/usr/bin/env python3

import indi_allsky
import argparse
import logging

from indi_allsky import IndiAllSkyConfigUtil


# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
# logger config in indi_allsky/flask/__init__.py

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() #%(lineno)d: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='configuration management actions',
        choices=(
            'bootstrap',
            'load',
            'update_level',
            'edit',
            'revert',
            'dump',
        ),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
    )
    argparser.add_argument(
        '--id',
        '-i',
        help='config id (revert/dump)',
        type=int,
    )


    args = argparser.parse_args()


    iacu = IndiAllSkyConfigUtil()
    action_func = getattr(iacu, args.action)
    action_func(config=args.config, config_id=args.id)

