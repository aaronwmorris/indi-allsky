from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import CertificateValidationFailure
#from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import requests
import io
import time
import socket
import json
import hashlib
import logging

logger = logging.getLogger('indi_allsky')


### UNTESTED

class requests_wsapi_sync(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(requests_wsapi_sync, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None


    def connect(self, *args, **kwargs):
        super(requests_wsapi_sync, self).connect(*args, **kwargs)

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
        }


        if cert_bypass:
            self.cert_bypass = True



    def close(self):
        super(requests_wsapi_sync, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(requests_wsapi_sync, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']
        metadata = kwargs['metadata']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)


        url = '{0:s}/{1:s}'.format(self.url, str(remote_file_p))
        logger.info('requests URL: %s', url)


        start = time.time()

        files = [
            ('metadata', ('metadata.json', io.StringIO(json.dumps(metadata)), 'application/json')),
            ('media', ('media.bin', io.open(str(local_file_p), 'rb'), 'application/octet-stream')),
        ]


        try:
            r = self.client.post(url, files=files, headers=self.headers, verify=self.verify)
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e



        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


