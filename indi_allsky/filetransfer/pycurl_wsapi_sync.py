from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import pycurl
import io
import time
import json
import hashlib
import logging

logger = logging.getLogger('indi_allsky')


class pycurl_wsapi_sync(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_wsapi_sync, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None


    def connect(self, *args, **kwargs):
        super(pycurl_wsapi_sync, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function
        ### The curl instance is just setup here

        endpoint_url = kwargs['hostname']
        username = kwargs['username']
        apikey = kwargs['apikey']
        cert_bypass = kwargs.get('cert_bypass')

        self.url = endpoint_url

        time_floor = int(time.time() / 300) * 300
        apikey_hash = hashlib.sha256('{0:d}{1:s}'.format(time_floor, apikey).encode()).hexdigest()


        self.client = pycurl.Curl()
        #self.client.setopt(pycurl.VERBOSE, 1)

        self.client.setopt(pycurl.HTTPHEADER, ['Authorization: Bearer {0:s}:{1:s}'.format(username, apikey_hash)])

        # deprecated: will be replaced by PROTOCOLS_STR
        self.client.setopt(pycurl.PROTOCOLS, pycurl.PROTO_HTTP | pycurl.PROTO_HTTPS)

        self.client.setopt(pycurl.CONNECTTIMEOUT, int(self._timeout))

        self.client.setopt(pycurl.FOLLOWLOCATION, 1)

        #self.client.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_2)

        if cert_bypass:
            self.client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
            self.client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication


        # Apply custom options from config
        libcurl_opts = self.config['FILETRANSFER'].get('LIBCURL_OPTIONS', {})
        for k, v in libcurl_opts.items():
            # Not catching any exceptions here
            # Options are validated in web config

            if k.startswith('#'):
                # comment
                continue

            if k.startswith('CURLOPT_'):
                # remove CURLOPT_ prefix
                k = k[8:]

            curlopt = getattr(pycurl, k)
            self.client.setopt(curlopt, v)



    def close(self):
        super(pycurl_wsapi_sync, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(pycurl_wsapi_sync, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']
        metadata = kwargs['metadata']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)


        url = '{0:s}/{1:s}'.format(self.url, str(remote_file_p))
        logger.info('pycurl URL: %s', url)


        start = time.time()
        f_localfile = io.open(str(local_file_p), 'rb')

        self.client.setopt(pycurl.URL, url)
        self.client.setopt(pycurl.POST, 1)


        self.client.setopt(pycurl.HTTPPOST, [('metadata', (pycurl.FORM_BUFFER, 'metadata.json', pycurl.FORM_BUFFERPTR, json.dumps(metadata)))])
        self.client.setopt(pycurl.HTTPPOST, [('media', (pycurl.FORM_FILE, str(local_file_p)))])


        try:
            self.client.perform()
        except pycurl.error as e:
            rc, msg = e.args

            if rc in [pycurl.E_LOGIN_DENIED]:
                raise AuthenticationFailure(msg) from e
            elif rc in [pycurl.E_COULDNT_RESOLVE_HOST]:
                raise ConnectionFailure(msg) from e
            elif rc in [pycurl.E_COULDNT_CONNECT]:
                raise ConnectionFailure(msg) from e
            elif rc in [pycurl.E_OPERATION_TIMEDOUT]:
                raise ConnectionFailure(msg) from e
            elif rc in [pycurl.E_PEER_FAILED_VERIFICATION]:
                raise CertificateValidationFailure(msg) from e
            elif rc in [pycurl.E_REMOTE_FILE_NOT_FOUND]:
                logger.error('Upload failed.  PycURL does not support relative path names')
                raise TransferFailure(msg) from e
            else:
                raise e from e


        f_localfile.close()

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


