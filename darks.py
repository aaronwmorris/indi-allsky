#!/usr/bin/env python3

import indi_allsky
import argparse
import logging

from indi_allsky import IndiAllSkyDarks


# setup flask context for db access
app = indi_allsky.flask.create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')
# logger config in indi_allsky/flask/__init__.py

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() #%(lineno)d: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.addHandler(LOG_HANDLER_STREAM)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=(
            'flush',
            'average',
            'sigma',
        ),
    )
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        default='/etc/indi-allsky/config.json',
    )
    argparser.add_argument(
        '--count',
        '-C',
        help='average image count',
        type=int,
        default=10,
    )


    args = argparser.parse_args()


    iad = IndiAllSkyDarks(args.config)
    iad.count = args.count

    action_func = getattr(iad, args.action)
    action_func()


