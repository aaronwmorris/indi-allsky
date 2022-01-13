from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import PermissionFailure

import pycurl
import io
import time
import logging

logger = logging.getLogger('indi_allsky')


class pycurl_ftps(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_ftps, self).__init__(*args, **kwargs)

        self.port = 990
        self.url = None


    def __del__(self):
        super(pycurl_ftps, self).__del__()


    def _connect(self, hostname, username, password):
        ### The full connect and transfer happens under the _put() function
        ### The curl instance is just setup here
        self.url = 'ftps://{0:s}:{1:d}'.format(hostname, self.port)

        client = pycurl.Curl()
        #client.setopt(pycurl.VERBOSE, 1)
        client.setopt(pycurl.CONNECTTIMEOUT, int(self.timeout))

        client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(username, password))

        #client.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_2)
        client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
        client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication

        return client


    def _close(self):
        if self.client:
            self.client.close()


    def _put(self, localfile, remotefile):
        pre_commands = [
            'SITE CHMOD 755 {0:s}'.format(str(remotefile.parent)),
        ]

        post_commands = [
            'SITE CHMOD 644 {0:s}'.format(str(remotefile)),
        ]

        url = '{0:s}/{1:s}'.format(self.url, str(remotefile))
        logger.info('pycurl URL: %s', url)


        start = time.time()
        f_localfile = io.open(str(localfile), 'rb')

        self.client.setopt(pycurl.URL, url)
        self.client.setopt(pycurl.FTP_CREATE_MISSING_DIRS, 1)
        self.client.setopt(pycurl.PREQUOTE, pre_commands)
        self.client.setopt(pycurl.POSTQUOTE, post_commands)
        self.client.setopt(pycurl.UPLOAD, 1)
        self.client.setopt(pycurl.READDATA, f_localfile)
        self.client.setopt(
            pycurl.INFILESIZE_LARGE,
            localfile.stat().st_size,
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
        local_file_size = localfile.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


# alias
class ftps(pycurl_ftps):
    pass

