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
import socket
import ssl
import json
import hashlib
import logging

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


logger = logging.getLogger('indi_allsky')


class requests_syncapi_v1(GenericFileTransfer):

    def __init__(self, *args, **kwargs):
        super(requests_syncapi_v1, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None


    def connect(self, *args, **kwargs):
        super(requests_syncapi_v1, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function

        endpoint_url = kwargs['hostname']
        username = kwargs['username']
        apikey = kwargs['apikey']
        cert_bypass = kwargs.get('cert_bypass')


        if cert_bypass:
            self.verify = False
        else:
            self.verify = True


        self.url = endpoint_url

        time_floor = int(time.time() / 300) * 300
        apikey_hash = hashlib.sha256('{0:d}{1:s}'.format(time_floor, apikey).encode()).hexdigest()


        self.client = requests

        self.headers = {
            'Authorization' : 'Bearer {0:s}:{1:s}'.format(username, apikey_hash),
            'Connection'    : 'close',  # no need for keep alives
        }


        if cert_bypass:
            self.cert_bypass = True



    def close(self):
        super(requests_syncapi_v1, self).close()


    def put(self, *args, **kwargs):
        super(requests_syncapi_v1, self).put(*args, **kwargs)

        metadata = kwargs['metadata']
        local_file = kwargs['local_file']


        #logger.info('requests URL: %s', url)


        files = [
            ('metadata', ('metadata.json', io.StringIO(json.dumps(metadata)), 'application/json')),
        ]


        # cameras do not have files
        if str(local_file) != 'camera':
            local_file_p = Path(local_file)
            files.append(('media', (local_file_p.name, io.open(str(local_file_p), 'rb'), 'application/octet-stream')))  # need file extension from original file


        start = time.time()

        try:
            r = self.client.post(self.url, files=files, headers=self.headers, verify=self.verify)
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ssl.SSLCertVerificationError as e:
            raise CertificateValidationFailure(str(e)) from e
        except requests.exceptions.SSLError as e:
            raise CertificateValidationFailure(str(e)) from e


        if r.status_code >= 400:
            raise TransferFailure('Sync error: {0:d}'.format(r.status_code))


        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


