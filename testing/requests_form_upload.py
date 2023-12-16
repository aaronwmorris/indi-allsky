#!/usr/bin/env python3

import sys
import io
from datetime import datetime
import time
import math
import hmac
import hashlib
import requests
from requests_toolbelt import MultipartEncoder
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
        username = 'foobar33'
        apikey = '0000000000000000000000000000000000000000000000000000000000000000'
        camera_uuid = '00000000-0000-0000-0000-000000000000'
        cert_bypass = True

        if cert_bypass:
            verify = False
        else:
            verify = True


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
            'width'        : 1920,
            'height'       : 1080,
            'process_elapsed' : 1.2,
            'camera_uuid'  : camera_uuid,
        }


        video_metadata = {  # noqa: F841
            'type'       : constants.VIDEO,
            'createDate' : now.timestamp(),
            'dayDate'    : now.strftime('%Y%m%d'),
            'night'      : True,
            'camera_uuid': camera_uuid,
        }


        get_params = {  # noqa: F841
            'id'           : 2,
            'camera_uuid'  : camera_uuid,
        }

        delete_metadata = {  # noqa: F841
            'id'           : 1,
            'camera_uuid'  : camera_uuid,
        }


        local_file_p = self.cur_dur / 'testing' / 'blob_detection' / 'test_no_clouds.jpg'
        #local_file_p = self.cur_dur.parent.parent / 'allsky-timelapse_ccd1_20230302_night.mp4'


        metadata = image_metadata
        #metadata = video_metadata

        metadata['file_size'] = local_file_p.stat().st_size  # needed to validate

        json_metadata = json.dumps(metadata)


        fields = {  # noqa: F841
            'metadata' : ('metadata.json', io.StringIO(json_metadata), 'application/json'),
            'media'    : (local_file_p.name, io.open(str(local_file_p), 'rb'), 'application/octet-stream'),  # need file extension from original file
        }


        mp_enc = MultipartEncoder(fields=fields)


        time_floor = math.floor(time.time() / 300)

        # data is received as bytes
        hmac_message = str(time_floor).encode() + json_metadata.encode()
        #logger.info('Data: %s', str(hmac_message))

        message_hmac = hmac.new(
            apikey.encode(),
            msg=hmac_message,
            digestmod=hashlib.sha3_512,
        ).hexdigest()


        self.headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(username, message_hmac),
            'Connection'    : 'close',  # no need for keep alives
            'Content-Type'  : mp_enc.content_type,
        }


        logger.info('Headers: %s', self.headers)

        start = time.time()

        #r = requests.get(endpoint_url, params=get_params, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
        r = requests.post(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
        #r = requests.put(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
        #r = requests.delete(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        logger.warning('Error: %d', r.status_code)
        logger.warning('Response: %s', json.loads(r.text))




if __name__ == "__main__":
    fu = FormUploader()
    fu.main()

