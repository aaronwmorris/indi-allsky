from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import CertificateValidationFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import io
import time
import logging

logger = logging.getLogger('indi_allsky')


class pycurl_ftpes(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(pycurl_ftpes, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 21
        self.url = None


    def connect(self, *args, **kwargs):
        super(pycurl_ftpes, self).connect(*args, **kwargs)

        import pycurl


        ### The full connect and transfer happens under the put() function
        ### The curl instance is just setup here

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']
        cert_bypass = kwargs.get('cert_bypass')

        self.url = 'ftp://{0:s}:{1:d}'.format(hostname, self._port)  # ftp:// is correct for FTPES

        self.client = pycurl.Curl()
        #self.client.setopt(pycurl.VERBOSE, 1)

        # deprecated: will be replaced by PROTOCOLS_STR
        self.client.setopt(pycurl.PROTOCOLS, pycurl.PROTO_FTP | pycurl.PROTO_FTPS)

        self.client.setopt(pycurl.CONNECTTIMEOUT, int(self.connect_timeout))
        self.client.setopt(pycurl.TIMEOUT, int(self.timeout))
        self.client.setopt(pycurl.FTP_CREATE_MISSING_DIRS, 1)

        self.client.setopt(pycurl.USERPWD, '{0:s}:{1:s}'.format(username, password))

        self.client.setopt(pycurl.FTP_SSL, pycurl.FTPSSL_ALL)
        self.client.setopt(pycurl.FTPSSLAUTH, pycurl.FTPAUTH_DEFAULT)

        #self.client.setopt(pycurl.SSLVERSION, pycurl.SSLVERSION_TLSv1_2)

        if cert_bypass:
            self.client.setopt(pycurl.SSL_VERIFYPEER, False)  # trust verification
            self.client.setopt(pycurl.SSL_VERIFYHOST, False)  # host verfication


        if self.config['FILETRANSFER'].get('FORCE_IPV4'):
            self.client.setopt(pycurl.IPRESOLVE, pycurl.IPRESOLVE_V4)
        elif self.config['FILETRANSFER'].get('FORCE_IPV6'):
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
        super(pycurl_ftpes, self).close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(pycurl_ftpes, self).put(*args, **kwargs)

        import pycurl


        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)

        #pre_commands = [
        #]

        post_commands = [
            'SITE CHMOD 644 {0:s}'.format(str(remote_file_p)),
            'SITE CHMOD 755 {0:s}'.format(str(remote_file_p.parent)),
        ]


        if self.atomic:
            # upload to a tmp name and rename
            remote_parent = remote_file_p.parent
            temp_filename = self.tempname(suffix=remote_file_p.suffix)

            final_file_p = remote_file_p
            remote_file_p = remote_parent.joinpath(temp_filename)

            post_commands.insert(0, '*DELE {0:s}'.format(str(final_file_p)))  # asterisk command allowed to fail
            post_commands.insert(1, 'RNFR {0:s}'.format(str(remote_file_p)))
            post_commands.insert(2, 'RNTO {0:s}'.format(str(final_file_p)))


        url = '{0:s}/{1:s}'.format(self.url, str(remote_file_p))
        logger.info('pycurl URL: %s', url)


        start = time.time()
        f_localfile = io.open(str(local_file_p), 'rb')

        self.client.setopt(pycurl.URL, url)
        #self.client.setopt(pycurl.PREQUOTE, pre_commands)
        self.client.setopt(pycurl.POSTQUOTE, post_commands)
        self.client.setopt(pycurl.UPLOAD, 1)
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
            elif rc in [pycurl.E_URL_MALFORMAT]:
                raise ConnectionFailure(msg) from e
            elif rc in [pycurl.E_PEER_FAILED_VERIFICATION]:
                raise CertificateValidationFailure(msg) from e
            elif rc in [pycurl.E_REMOTE_ACCESS_DENIED]:
                raise TransferFailure(msg) from e
            elif rc in [pycurl.E_REMOTE_FILE_NOT_FOUND]:
                logger.error('Upload failed.  PycURL does not support relative path names')
                raise TransferFailure(msg) from e
            elif rc in [pycurl.E_QUOTE_ERROR]:
                logger.warning('PycURL quoted commands encountered an error (safe to ignore)')
                pass
            else:
                raise e from e
        finally:
            f_localfile.close()


        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


# alias
class ftpes(pycurl_ftpes):
    pass

