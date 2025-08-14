#!/usr/bin/env python3
# Example of a pre-save image hook
# The pre-save script is executed concurrently while the image is being processed but before it is saved.
#
# STDOUT and STDERR are ignored
#
# The json output file is set in the environment variable DATA_JSON


import sys
import os
import json
import io
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


try:
    # data file is communicated via environment variable
    data_file = os.environ['DATA_JSON']
except KeyError:
    logger.error('DATA_JSON environment variable not defined')
    sys.exit(1)


# dict to be used for json data
# All data is optional
# All data should be returned as strings
data = {
    'custom_1' : 'Exposure: {0:0.6f}'.format(float(os.environ['EXPOSURE'])),
    'custom_2' : 'Gain: {0:d}'.format(int(os.environ['GAIN'])),
    'custom_3' : 'Latitude: {0:0.1f}'.format(float(os.environ['LATITUDE'])),
    'custom_4' : 'Longitude: {0:0.1f}'.format(float(os.environ['LONGITUDE'])),
    'custom_5' : 'Sun Altitude: {0:0.1f}'.format(float(os.environ['SUNALT'])),
    'custom_6' : 'Moon Altitude: {0:0.1f}'.format(float(os.environ['MOONALT'])),
    'custom_7' : 'Moon Phase:: {0:0.1f}'.format(float(os.environ['MOONPHASE'])),
    'custom_8' : 'Sensor Temp 10: {0:0.1f}'.format(float(os.environ['SENSOR_TEMP_10'])),
    'custom_9' : 'User Sensor 10: {0:0.1f}'.format(float(os.environ['SENSOR_USER_10'])),
}


# json data file is optional
with io.open(data_file, 'w') as data_f:
    json.dump(data, data_f, indent=4)


# script must return exit code 0 for success
sys.exit(0)
