#!/usr/bin/env python3
# Example of a post-save image hook
# STDOUT and STDERR are ignored


import sys
from pathlib import Path
import argparse
import signal
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


# Available environment variables with data.  Environment variables are strings, therefore
# it requires using int() or float() to convert to numbers
#EXPOSURE   : float
#GAIN       : int
#BIN        : int
#SUNALT     : float
#MOONALT    : float
#MOONPHASE  : float
#NIGHT      : int
#MOONMODE   : float
#LATITUDE   : float
#LONGITUDE  : float
#ELEVATION  : int
#SENSOR_TEMP_0 - SENSOR_TEMP_29 : float
#SENSOR_USER_0 - SENSOR_USER_29 : float


def sigint_handler(signum, frame):
    # this prevents a keyboard interrupt from stopping the script
    pass


signal.signal(signal.SIGINT, sigint_handler)


argparser = argparse.ArgumentParser()
argparser.add_argument(
    'image_file',
    help='Image File',
    type=str,
)

args = argparser.parse_args()


image_path = Path(args.image_file)


if not image_path.is_file():
    logger.error('Image does not exist')
    sys.exit(1)


# At this stage of the script, you may read the image, transfer the image, fire ze missiles, etc
# It is recommended not to alter the image


# script must exist with exit code 0 for success
sys.exit(0)
