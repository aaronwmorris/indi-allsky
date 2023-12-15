from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import requests
import io
import time
import math
import socket
import ssl
import json
import hashlib
import hmac
import logging

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logger = logging.getLogger('indi_allsky')


class requests_syncapi_v1(GenericFileTransfer):

    time_skew = 300  # number of seconds the client is allowed to deviate from server


    def __init__(self, *args, **kwargs):
        super(requests_syncapi_v1, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None
        self.apikey = None


    def connect(self, *args, **kwargs):
        super(requests_syncapi_v1, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function

        endpoint_url = kwargs['hostname']
        self.username = kwargs['username']
        self.apikey = kwargs['apikey']
        cert_bypass = kwargs.get('cert_bypass')


        if cert_bypass:
            self.verify = False
        else:
            self.verify = True


        self.url = endpoint_url


        self.client = requests


        if cert_bypass:
            self.cert_bypass = True



    def close(self):
        super(requests_syncapi_v1, self).close()


    def put(self, *args, **kwargs):
        super(requests_syncapi_v1, self).put(*args, **kwargs)

        metadata = kwargs['metadata']
        local_file = kwargs['local_file']
        empty_file = kwargs['empty_file']


        #logger.info('requests URL: %s', self.url)

        # cameras do not have files
        if str(local_file) == 'camera':
            local_file_p = Path('bogus.ext')
            local_file_size = 1024  # fake
            f_media = io.BytesIO(b'')  # no data
            metadata['file_size'] = 0
        else:
            # all other entry types
            local_file_p = Path(local_file)

            if not empty_file:
                local_file_size = local_file_p.stat().st_size
                metadata['file_size'] = local_file_size  # needed to validate
                f_media = io.open(str(local_file_p), 'rb')
            else:
                local_file_size = 1024  # fake
                f_media = io.BytesIO(b'')  # no data
                metadata['file_size'] = 0


        json_metadata = json.dumps(metadata)
        f_metadata = io.StringIO(json_metadata)


        time_floor = math.floor(time.time() / self.time_skew)

        # data is received as bytes
        hmac_message = str(time_floor).encode() + json_metadata.encode()

        message_hmac = hmac.new(
            self.apikey.encode(),
            msg=hmac_message,
            digestmod=hashlib.sha3_512,
        ).hexdigest()


        headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(self.username, message_hmac),
            'Connection'    : 'close',  # no need for keep alives
        }


        files = [
            (
                'metadata',
                (
                    'metadata.json',
                    f_metadata,
                    'application/json',
                )
            ),
            (
                'media', (
                    local_file_p.name,  # need file extension from original file
                    f_media,
                    'application/octet-stream',
                )
            ),
        ]


        start = time.time()

        try:
            # put allows overwrites
            r = self.client.put(self.url, files=files, headers=headers, verify=self.verify, stream=True, timeout=(self.connect_timeout, self.timeout))
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ReadTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except ssl.SSLCertVerificationError as e:
            raise CertificateValidationFailure(str(e)) from e
        except requests.exceptions.SSLError as e:
            raise CertificateValidationFailure(str(e)) from e
        finally:
            f_metadata.close()
            f_media.close()


        if r.status_code >= 400:
            raise TransferFailure('Sync error: {0:d}'.format(r.status_code))


        upload_elapsed_s = time.time() - start
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


        return json.loads(r.text)

