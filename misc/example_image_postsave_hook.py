#!/usr/bin/env python3
# Example of a post-save image hook
# The post-save script is executed after the image is processed and saved.
#
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
#EXPOSURE   : float(os.environ['EXPOSURE'])
#GAIN       : int(os.environ['GAIN'])
#BIN        : int(os.environ['BIN'])
#SUNALT     : float(os.environ['SUNALT'])
#MOONALT    : float(os.environ['MOONALT'])
#MOONPHASE  : float(os.environ['MOONPHASE'])
#NIGHT      : int(os.environ['NIGHT'])
#MOONMODE   : int(os.environ['MOONMODE'])
#LATITUDE   : float(os.environ['LATITUDE'])
#LONGITUDE  : float(os.environ['LONGITUDE'])
#ELEVATION  : int(os.environ['ELEVATION'])
#SENSOR_TEMP_0 - SENSOR_TEMP_59 : float(os.environ['SENSOR_TEMP_##'])
#SENSOR_USER_0 - SENSOR_USER_59 : float(os.environ['SENSOR_USER_##'])


def sigint_handler(signum, frame):
    # this prevents a keyboard interrupt from stopping the script
    pass


signal.signal(signal.SIGINT, sigint_handler)


#############
### START ###
#############


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


# script must return exit code 0 for success
sys.exit(0)
