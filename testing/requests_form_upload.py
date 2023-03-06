#!/usr/bin/env python3

import sys
import io
from datetime import datetime
import time
import hashlib
import requests
import json
from pathlib import Path
import http.client as http_client
import logging

sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky import constants


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
        endpoint_url = 'https://localhost/indi-allsky/sync/v1/image'
        #endpoint_url = 'https://localhost/indi-allsky/sync/v1/video'
        username = 'foobar'
        apikey = 'd8389bda9ac722e4619ca6d1dbe41cc8422d8fc26a111784b00617a87fe7889c'
        cert_bypass = True

        if cert_bypass:
            verify = False
        else:
            verify = True

        time_floor = int(time.time() / 300) * 300

        apikey_hash = hashlib.sha256('{0:d}{1:s}'.format(time_floor, apikey).encode()).hexdigest()
        #logger.info('Hash: %s', apikey_hash)


        self.headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(username, apikey_hash),
        }


        now = datetime.now()

        image_metadata = {  # noqa: F841
            'type'         : constants.IMAGE,
            'createDate'   : now.timestamp(),
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
            'camera_uuid'  : '05415368-2ff1-4098-a1a6-5ff75e2b1330',
        }


        video_metadata = {  # noqa: F841
            'type'       : constants.VIDEO,
            'createDate' : now.timestamp(),
            'dayDate'    : now.strftime('%Y%m%d'),
            'night'      : True,
            'camera_uuid': '05415368-2ff1-4098-a1a6-5ff75e2b1330',
        }


        get_params = {  # noqa: F841
            'id' : 2,
        }

        delete_metadata = {  # noqa: F841
            'id' : 1,
        }


        local_image_file_p = self.cur_dur / 'testing' / 'blob_detection' / 'test_no_clouds.jpg'
        #local_video_file_p = self.cur_dur.parent.parent / 'allsky-timelapse_ccd1_20230302_night.mp4'


        files = [  # noqa: F841
            ('metadata', ('metadata.json', io.StringIO(json.dumps(image_metadata)), 'application/json')),
            ('media', (local_image_file_p.name, io.open(str(local_image_file_p), 'rb'), 'application/octet-stream')),  # need file extension from original file
            #('metadata', ('metadata.json', io.StringIO(json.dumps(video_metadata)), 'application/json')),
            #('media', (local_video_file_p.name, io.open(str(local_video_file_p), 'rb'), 'application/octet-stream')),  # need file extension from original file
        ]

        start = time.time()

        #r = requests.get(endpoint_url, params=get_params, headers=self.headers, verify=verify)
        r = requests.post(endpoint_url, files=files, headers=self.headers, verify=verify)
        #r = requests.put(endpoint_url, files=files, headers=self.headers, verify=verify)
        #r = requests.delete(endpoint_url, files=delete_metadata, headers=self.headers, verify=verify)

        upload_elapsed_s = time.time() - start
        local_file_size = local_image_file_p.stat().st_size
        #local_file_size = local_video_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        logger.warning('Error: %d', r.status_code)
        logger.warning('Response: %s', json.loads(r.text))




if __name__ == "__main__":
    fu = FormUploader()
    fu.main()

