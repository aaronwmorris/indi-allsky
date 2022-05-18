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
            'tempaverage',
            'sigmaclip',
            'tempsigmaclip',
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
        help='image count',
        type=int,
        default=10,
    )
    argparser.add_argument(
        '--temp_delta',
        '-t',
        help='temperature delta between dark frame sets',
        type=float,
        default=5.0,
    )
    argparser.add_argument(
        '--time_delta',
        '-T',
        help='time delta between dark frame exposures',
        type=int,
        default=5,
    )
    argparser.add_argument(
        '--bitmax',
        '-b',
        help='max bits returned by camera if different than container',
        type=int,
        default=0,
    )


    args = argparser.parse_args()


    iad = IndiAllSkyDarks(args.config)
    iad.count = args.count
    iad.temp_delta = args.temp_delta
    iad.time_delta = args.time_delta
    iad.bitmax = args.bitmax

    action_func = getattr(iad, args.action)
    action_func()


