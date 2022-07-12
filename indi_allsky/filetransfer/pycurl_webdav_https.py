from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import pycurl
import io
import time
import logging

logger = logging.getLogger('indi_allsky')


class pycurl_webdav_https(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_webdav_https, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 443
        self.url = None


    def connect(self, *args, **kwargs):
        super(pycurl_webdav_https, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function
        ### The curl instance is just setup here

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']

        self.url = 'https://{0:s}:{1:d}'.format(hostname, self._port)

        self.client = pycurl.Curl()
        #self.client.setopt(pycurl.VERBOSE, 1)
        self.client.setopt(pycurl.CONNECTTIMEOUT, int(self._timeout))

        self.client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(username, password))

        #self.client.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_2)
        self.client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
        self.client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication


    def close(self):
        super(pycurl_webdav_https, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(pycurl_webdav_https, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)

        url = '{0:s}/{1:s}'.format(self.url, str(remote_file_p))
        logger.info('pycurl URL: %s', url)


        start = time.time()
        f_localfile = io.open(str(local_file_p), 'rb')

        self.client.setopt(pycurl.URL, url)
        self.client.setopt(pycurl.UPLOAD, 1)
        self.client.setopt(pycurl.FOLLOWLOCATION, 1)
        #self.client.setopt(pycurl.HTTPHEADER, ['Transfer-Encoding: chunked'])
        self.client.setopt(pycurl.HTTPAUTH, pycurl.HTTPAUTH_ANY)
        self.client.setopt(pycurl.READDATA, f_localfile)
        self.client.setopt(
            pycurl.INFILESIZE_LARGE,
            local_file_p.stat().st_size,
        )

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
            else:
                raise e from e


        f_localfile.close()

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


