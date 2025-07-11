#!/usr/bin/env python3

# Example of an external temperature script for indi-allsky
# STDOUT and STDERR are ignored
#
# The json output file is set in the environment variable TEMP_JSON


import os
import sys
import io
import json
import signal
import logging


logging.basicConfig(level=logging.INFO)
logger = logging


def sigint_handler(signum, frame):
    # this prevents a keyboard interrupt from stopping the script
    pass


signal.signal(signal.SIGINT, sigint_handler)


#############
### START ###
#############


temp_c = -5.111

try:
    # data file is communicated via environment variable
    temp_json = os.environ['TEMP_JSON']
except KeyError:
    logger.error('TEMP_JSON environment variable is not defined')
    sys.exit(1)


# dict to be used for json data
temp_data = {
    'temp' : temp_c,
}


# write json data
with io.open(temp_json, 'w') as f_temp_json:
    json.dump(temp_data, f_temp_json, indent=4)


# script must exist with exit code 0 for success
sys.exit(0)

