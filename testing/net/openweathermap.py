#!/usr/bin/env python3

import argparse
import requests
from pprint import pformat
import logging


LATITUDE = 33.0
LONGITUDE = -84.0

#UNITS = 'standard'
UNITS = 'metric'



logging.basicConfig(level=logging.INFO)
logger = logging


class OpenWeatherMapTest(object):

    def main(self, apikey):
        url = 'https://api.openweathermap.org/data/2.5/weather?lat={0:0.1f}&lon={1:0.1f}&units={2:s}&appid={3:s}'.format(LATITUDE, LONGITUDE, UNITS, apikey)
        #url = 'https://api.openweathermap.org/data/3.0/onecall?lat={0:0.1f}&lon={1:0.1f}&units={2:s}&appid={3:s}'.format(LATITUDE, LONGITUDE, UNITS, apikey)

        logger.warning('URL: %s', url)
        r = requests.get(url, verify=True, timeout=(15.0, 30.0))

        if r.status_code >= 400:
            logger.error('URL returned %d', r.status_code)
            return

        r_data = r.json()

        logger.info('Response: %s', pformat(r_data))


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'apikey',
        help='apikey',
        type=str,
    )

    args = argparser.parse_args()


    o = OpenWeatherMapTest()
    o.main(args.apikey)

