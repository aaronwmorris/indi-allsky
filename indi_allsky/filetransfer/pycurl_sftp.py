from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import pycurl
import io
import time
import logging

logger = logging.getLogger('indi_allsky')


class pycurl_sftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_sftp, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 22
        self.url = None


    def connect(self, *args, **kwargs):
        super(pycurl_sftp, self).connect(*args, **kwargs)

        ### The full connect and transfer happens under the put() function
        ### The curl instance is just setup here

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']

        self.url = 'sftp://{0:s}:{1:d}'.format(hostname, self._port)

        self.client = pycurl.Curl()
        #self.client.setopt(pycurl.VERBOSE, 1)

        # deprecated: will be replaced by PROTOCOLS_STR
        self.client.setopt(pycurl.PROTOCOLS, pycurl.PROTO_SFTP)

        self.client.setopt(pycurl.CONNECTTIMEOUT, int(self._timeout))
        self.client.setopt(pycurl.FTP_CREATE_MISSING_DIRS, 1)

        #self.client.setopt(pycurl.SSH_KNOWNHOSTS, '/dev/null')
        #self.client.setopt(pycurl.SSH_KEYFUNCTION, self.accept_new_hosts)

        self.client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(username, password))


        # Apply custom options from config
        libcurl_opts = self.config['FILETRANSFER'].get('LIBCURL_OPTIONS', {})
        for k, v in libcurl_opts.items():
            # Not catching any exceptions here
            # Options are validated in web config

            if k.startswith('CURLOPT_'):
                # remove CURLOPT_ prefix
                k = k[8:]

            curlopt = getattr(pycurl, k)
            self.client.setopt(curlopt, v)


    #def accept_new_hosts(known_key, found_key, match):
    #    return pycurl.KHSTAT_FINE


    def close(self):
        super(pycurl_sftp, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(pycurl_sftp, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)

        #pre_commands = [
        #]

        post_commands = [
            'chmod 644 {0:s}'.format(str(remote_file_p)),
            'chmod 755 {0:s}'.format(str(remote_file_p.parent)),
        ]

        url = '{0:s}/{1:s}'.format(self.url, str(remote_file_p))
        logger.info('pycurl URL: %s', url)


        start = time.time()
        f_localfile = io.open(str(local_file_p), 'rb')

        self.client.setopt(pycurl.URL, url)
        #self.client.setopt(pycurl.PREQUOTE, pre_commands)
        self.client.setopt(pycurl.POSTQUOTE, post_commands)
        self.client.setopt(pycurl.UPLOAD, 1)
        self.client.setopt(pycurl.READDATA, f_localfile)

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
            elif rc in [pycurl.E_QUOTE_ERROR]:
                #logger.warning('PyCurl quoted commands encountered an error (safe to ignore)')
                pass
            else:
                raise e from e


        f_localfile.close()

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


#alias
class sftp(pycurl_sftp):
    pass

