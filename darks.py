#!/usr/bin/env python3

import argparse
import json
import locale
import multiprocessing
import logging
import signal
import sys


logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.addHandler(LOG_HANDLER_STREAM)


def build_arg_parser():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='dark frame algorithm, sigmaclip is recommended. Note: you must use AVERAGE mode when generating darks from RGB/JPEG data',
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
        help='image count [default: 10]',
        type=int,
        default=10,
    )
    argparser.add_argument(
        '--gains',
        '-g',
        help='gain list [default: auto]',
        nargs='+',
        type=float,
        required=False,
    )
    argparser.add_argument(
        '--Binning',
        '-B',
        help='binning to use with gain list [default: 1]',
        type=int,
        default=1,
    )
    argparser.add_argument(
        '--temp_delta',
        '-t',
        help='temperature delta between dark frame sets [default: 5.0]',
        type=float,
        default=5.0,
    )
    argparser.add_argument(
        '--Time_delta',
        '-T',
        help='time delta (seconds) between dark frame exposures [default: 5]',
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
    argparser.add_argument(
        '--flush_id',
        '-f',
        help='flush camera id [default: 1]',
        type=int,
        default=1,
    )
    argparser.add_argument(
        '--automation-manifest',
        help=argparse.SUPPRESS,
        type=str,
        required=False,
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
    daytime_group.add_argument(
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
    return argparser


def configure_legacy_capture(capture, args):
    capture.count = args.Count
    capture.temp_delta = args.temp_delta
    capture.time_delta = args.Time_delta
    capture.bitmax = args.bitmax
    capture.daytime = args.daytime
    capture.reverse = args.reverse
    capture.flush_camera_id = args.flush_id
    capture.gain_list = args.gains
    capture.binning = args.Binning


def configure_automation_capture(capture, manifest):
    if not isinstance(manifest, dict) or not manifest.get('automation'):
        raise ValueError('Invalid automation manifest')

    capture.automation_manifest = manifest
    capture.count = manifest['frame_count']
    capture.reverse = manifest.get('capture_order', 'long_first') != 'short_first'
    capture.progress_file = manifest['progress_file']

    if manifest.get('temperature_series'):
        capture.temp_delta = manifest['temperature_delta']
        capture.temperature_target = manifest.get('temperature_target')
        return

    capture.capture_profile = manifest['capture_period']
    capture.binning = manifest['binning']
    capture.bitmax = manifest.get('bitmax') or 0
    capture.gain_list = manifest['gains']
    capture.exposure_list = manifest['exposures']


def main(argv=None):
    # should be inherited by all of the sub-processes
    locale.setlocale(locale.LC_ALL, '')

    # https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
    try:
        multiprocessing.set_start_method('fork', force=True)
    except RuntimeError:
        pass

    args = build_arg_parser().parse_args(argv)

    from indi_allsky.darks import DarkCapturePlanChanged
    from indi_allsky.darks import IndiAllSkyDarks

    capture = IndiAllSkyDarks()
    action_func = getattr(capture, args.action)

    if not args.automation_manifest:
        configure_legacy_capture(capture, args)
        action_func()
        return 0

    with open(args.automation_manifest, 'r', encoding='utf-8') as manifest_file:
        configure_automation_capture(capture, json.load(manifest_file))

    signal.signal(signal.SIGINT, capture.sigint_handler_main)
    signal.signal(signal.SIGTERM, capture.sigint_handler_main)

    try:
        action_func()
    except DarkCapturePlanChanged:
        logger.error('Live camera capabilities changed; plan review required')
        return 75
    except KeyboardInterrupt:
        logger.warning('Dark frame capture cancelled')
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
