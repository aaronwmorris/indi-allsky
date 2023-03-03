#!/usr/bin/env python3

import io
from datetime import datetime
import time
import hashlib
import requests
import json
from pathlib import Path
import http.client as http_client
import logging


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logging.basicConfig(level=logging.INFO)
logger = logging

http_client.HTTPConnection.debuglevel = 0
requests_log = logging.getLogger('requests.packages.urllib3')
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True


class FormUploader(object):

    def __init__(self):
        self.cur_dur = Path(__file__).parent.absolute().parent


    def main(self):
        endpoint_url = 'https://localhost/indi-allsky/upload/image'
        username = 'foobar'
        apikey = '3842b28bcdd1cb91fd4a996b963deffc3b4cb9ab95aa27e0d9301b4f91401f86'
        cert_bypass = True

        if cert_bypass:
            verify = False
        else:
            verify = True

        time_floor = int(time.time() / 300) * 300

        apikey_hash = hashlib.sha256('{0:d}{1:s}'.format(time_floor, apikey).encode()).hexdigest()
        logger.info('Hash: %s', apikey_hash)


        self.headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(username, apikey_hash),
        }


        metadata = {
            'createDate'   : datetime.now().timestamp(),
            'exposure'     : 5.6,
            'exp_elapsed'  : 1.1,
            'gain'         : 100,
            'binmode'      : 1,
            'temp'         : -6.7,
            'adu'          : 5006.2,
            'stable'       : True,
            'moonmode'     : False,
            'moonphase'    : 16.1,
            'night'        : True,
            'sqm'          : 5007.8,
            'adu_roi'      : False,
            'calibrated'   : True,
            'stars'        : 0,
            'detections'   : 0,
            'process_elapsed' : 1.2,
        }



        local_file_p = self.cur_dur / 'testing' / 'blob_detection' / 'test_no_clouds.jpg'


        files = [
            ('metadata', ('metadata.json', io.StringIO(json.dumps(metadata)), 'application/json')),
            ('media', (local_file_p.name, io.open(str(local_file_p), 'rb'), 'application/octet-stream')),
        ]


        r = requests.post(endpoint_url, files=files, headers=self.headers, verify=verify)

        logger.warning('Error: %d', r.status_code)




if __name__ == "__main__":
    fu = FormUploader()
    fu.main()

