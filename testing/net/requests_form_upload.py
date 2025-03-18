#!/usr/bin/env python3

import sys
import io
import argparse
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

from sqlalchemy.orm.exc import NoResultFound


sys.path.append(str(Path(__file__).parent.absolute().parent))

from indi_allsky import constants
from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig


# setup flask context for db access
app = create_app()
app.app_context().push()


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logging.basicConfig(level=logging.INFO)
logger = logging

http_client.HTTPConnection.debuglevel = 0
requests_log = logging.getLogger('requests.packages.urllib3')
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True


class FormUploader(object):

    time_skew = 300


    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


    def main(self, camera_uuid, media_file):
        local_file_p = Path(media_file)

        base_url = self.config['SYNCAPI']['BASEURL']
        username = self.config['SYNCAPI']['USERNAME']
        apikey = self.config['SYNCAPI']['APIKEY']

        endpoint_url = base_url + '/sync/v1/video'

        cert_bypass = True

        if cert_bypass:
            verify = False
        else:
            verify = True


        now = datetime.now()

        image_metadata = {  # noqa: F841
            'type'         : constants.IMAGE,
            'createDate'   : now.timestamp(),
            'dayDate'      : now.strftime('%Y%m%d'),
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


        metadata = image_metadata
        #metadata = video_metadata

        metadata['file_size'] = local_file_p.stat().st_size  # needed to validate

        json_metadata = json.dumps(metadata)


        fields = {  # noqa: F841
            'metadata' : ('metadata.json', io.StringIO(json_metadata), 'application/json'),
            'media'    : (local_file_p.name, io.open(str(local_file_p), 'rb'), 'application/octet-stream'),  # need file extension from original file
        }


        mp_enc = MultipartEncoder(fields=fields)


        time_floor = math.floor(time.time() / self.time_skew)
        logger.info('Time floor: %d', time_floor)

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

        try:
            #r = requests.get(endpoint_url, params=get_params, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
            r = requests.post(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
            #r = requests.put(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
            #r = requests.delete(endpoint_url, data=mp_enc, headers=self.headers, verify=verify, timeout=(5.0, 10.0))
        except requests.exceptions.ConnectTimeout as e:
            logger.error('Connect timeout: %s', str(e))
            sys.exit(1)
        except requests.exceptions.ReadTimeout as e:
            logger.error('Read timeout: %s', str(e))
            sys.exit(1)

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        logger.warning('Error: %d', r.status_code)
        logger.warning('Response: %s', json.loads(r.text))




if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'file',
        help='Input file',
        type=str,
    )
    argparser.add_argument(
        '--camera',
        '-c',
        help='camera uuid',
        type=str,
        required=True,
    )


    args = argparser.parse_args()

    fu = FormUploader()
    fu.main(args.camera, args.file)

