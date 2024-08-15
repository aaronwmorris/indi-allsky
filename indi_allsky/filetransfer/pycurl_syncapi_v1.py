from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import io
import time
import json
import hashlib
import logging

logger = logging.getLogger('indi_allsky')


### UNTESTED

class pycurl_syncapi_v1(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_syncapi_v1, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None


    def connect(self, *args, **kwargs):
        super(pycurl_syncapi_v1, self).connect(*args, **kwargs)

        import pycurl


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

        self.client.setopt(pycurl.CONNECTTIMEOUT, int(self.connect_timeout))
        self.client.setopt(pycurl.TIMEOUT, int(self.timeout))

        self.client.setopt(pycurl.FOLLOWLOCATION, 1)

        #self.client.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_2)

        if cert_bypass:
            self.client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
            self.client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication


        if self.config['FILETRANSFER'].get('FORCE_IPV4'):
            self.client.setopt(pycurl.IPRESOLVE, pycurl.IPRESOLVE_V4)

        if self.config['FILETRANSFER'].get('FORCE_IPV6'):
            self.client.setopt(pycurl.IPRESOLVE, pycurl.IPRESOLVE_V6)


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
        super(pycurl_syncapi_v1, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(pycurl_syncapi_v1, self).put(*args, **kwargs)

        import pycurl


        local_file = kwargs['local_file']
        metadata = kwargs['metadata']


        files = [(
            'metadata', (
                pycurl.FORM_BUFFER, 'metadata.json',
                pycurl.FORM_BUFFERPTR, json.dumps(metadata),
                pycurl.FORM_CONTENTTYPE, 'application/json',
            )
        )]


        # cameras do not have files
        if str(local_file) != 'camera':
            local_file_p = Path(local_file)
            local_file_size = local_file_p.stat().st_size

            files.append((
                'media', (
                    pycurl.FORM_FILE, str(local_file_p),
                    pycurl.FORM_FILENAME, local_file_p.name,  # need file extension from original file
                    pycurl.FORM_CONTENTTYPE, 'application/octet-stream',
                )
            ))
        else:
            local_file_size = 1024  # fake


        self.client.setopt(pycurl.HTTPPOST, files)


        start = time.time()

        self.client.setopt(pycurl.URL, self.url)

        #self.client.setopt(pycurl.POST, 1)
        self.client.setopt(pycurl.UPLOAD, 1)  # PUT


        response_buffer = io.BytesIO()
        self.client.setopt(pycurl.WRITEFUNCTION, response_buffer.write)


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
            elif rc in [pycurl.E_URL_MALFORMAT]:
                raise ConnectionFailure(msg) from e
            elif rc in [pycurl.E_PEER_FAILED_VERIFICATION]:
                raise CertificateValidationFailure(msg) from e
            elif rc in [pycurl.E_REMOTE_FILE_NOT_FOUND]:
                logger.error('Upload failed.  PycURL does not support relative path names')
                raise TransferFailure(msg) from e
            else:
                raise e from e


        upload_elapsed_s = time.time() - start
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


        response_str = response_buffer.getvalue().decode()
        logger.info('Response: %s', response_str)

        try:
            response = json.loads(response_str)
        except json.JSONDecodeError as e:
            raise TransferFailure(str(e)) from e


        return response

