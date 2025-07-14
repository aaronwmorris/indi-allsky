#!/usr/bin/env python3
# Example of a pre-capture hook
# The pre-capture script is executed before an image is captured
#
# STDOUT and STDERR are ignored


import sys
import signal
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


# Available environment variables with data.  Environment variables are strings, therefore
# it requires using int() or float() to convert to numbers
#GAIN       : int(os.environ['GAIN'])
#BIN        : int(os.environ['BIN'])
#NIGHT      : int(os.environ['NIGHT'])
#MOONMODE   : int(os.environ['MOONMODE'])
#LATITUDE   : float(os.environ['LATITUDE'])
#LONGITUDE  : float(os.environ['LONGITUDE'])
#ELEVATION  : int(os.environ['ELEVATION'])
#SENSOR_TEMP_0 - SENSOR_TEMP_29 : float(os.environ['SENSOR_TEMP_##'])
#SENSOR_USER_0 - SENSOR_USER_29 : float(os.environ['SENSOR_USER_##'])


def sigint_handler(signum, frame):
    # this prevents a keyboard interrupt from stopping the script
    pass


signal.signal(signal.SIGINT, sigint_handler)


#############
### START ###
#############


# Do something interesting here


# script must exist with exit code 0 for success
sys.exit(0)
