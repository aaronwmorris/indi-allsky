#!/usr/bin/env python3

import argparse
import logging

from indi_allsky.darks import IndiAllSkyDarks


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.addHandler(LOG_HANDLER_STREAM)



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='dark frame algorithm, sigmaclip is recommended',
        choices=(
            'flush',
            'average',
            'tempaverage',
            'sigmaclip',
            'tempsigmaclip',
        ),
    )
    argparser.add_argument(
        '--Count',
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
        '--Time_delta',
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


    reverse_group = argparser.add_mutually_exclusive_group(required=False)
    reverse_group.add_argument(
        '--reverse',
        help='take dark frames from highest to lowest exposure (default)',
        dest='reverse',
        action='store_true',
    )
    reverse_group.add_argument(
        '--no-reverse',
        help='take dark frames from lowest to highest exposure',
        dest='reverse',
        action='store_false',
    )
    reverse_group.set_defaults(reverse=True)


    daytime_group = argparser.add_mutually_exclusive_group(required=False)
    daytime_group .add_argument(
        '--daytime',
        help='enable daytime darks (default)',
        dest='daytime',
        action='store_true',
    )
    daytime_group.add_argument(
        '--no-daytime',
        help='disable daytime darks',
        dest='daytime',
        action='store_false',
    )
    daytime_group.set_defaults(daytime=True)


    args = argparser.parse_args()


    iad = IndiAllSkyDarks()
    iad.count = args.Count
    iad.temp_delta = args.temp_delta
    iad.time_delta = args.Time_delta
    iad.bitmax = args.bitmax
    iad.daytime = args.daytime
    iad.reverse = args.reverse

    action_func = getattr(iad, args.action)
    action_func()


