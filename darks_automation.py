#!/usr/bin/env python3

import argparse
import json
import locale
import logging
import multiprocessing
import signal
import sys


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(processName)s %(module)s.%(funcName)s() [%(lineno)d]: %(message)s',
)
logger = logging.getLogger('indi_allsky')


def configure_capture(capture, manifest):
    if not isinstance(manifest, dict) or not manifest.get('automation'):
        raise ValueError('Invalid automation manifest')

    method = str(manifest.get('method') or '')
    if method not in ('average', 'sigmaclip'):
        raise ValueError('Invalid dark stacking method')

    capture.automation_manifest = manifest
    capture.count = manifest['frame_count']
    capture.reverse = manifest.get('capture_order', 'long_first') != 'short_first'
    capture.progress_file = manifest['progress_file']

    if manifest.get('temperature_series'):
        capture.temp_delta = manifest['temperature_delta']
        capture.temperature_target = manifest.get('temperature_target')
        return 'temp{0:s}'.format(method)

    capture.capture_profile = manifest['capture_period']
    capture.binning = manifest['binning']
    capture.bitmax = manifest.get('bitmax') or 0
    capture.gain_list = manifest['gains']
    capture.exposure_list = manifest['exposures']
    return method


def main(argv=None):
    locale.setlocale(locale.LC_ALL, '')
    try:
        multiprocessing.set_start_method('fork', force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', help=argparse.SUPPRESS, required=True)
    args = parser.parse_args(argv)

    from indi_allsky.darks import DarkCapturePlanChanged
    from indi_allsky.darks import IndiAllSkyDarks

    with open(args.manifest, 'r', encoding='utf-8') as manifest_file:
        manifest = json.load(manifest_file)

    capture = IndiAllSkyDarks()
    action = configure_capture(capture, manifest)
    signal.signal(signal.SIGINT, capture.sigint_handler_main)
    signal.signal(signal.SIGTERM, capture.sigint_handler_main)

    try:
        getattr(capture, action)()
    except DarkCapturePlanChanged:
        logger.error('Live camera capabilities changed; plan review required')
        return 75
    except KeyboardInterrupt:
        logger.warning('Dark frame capture cancelled')
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
