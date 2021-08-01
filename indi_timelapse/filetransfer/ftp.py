from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import PermissionFailure

import ftplib
import io
import socket
import multiprocessing

logger = multiprocessing.get_logger()


class ftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(ftp, self).__init__(*args, **kwargs)

        self.port = 21


    def __del__(self):
        super(ftp, self).__del__()


    def _connect(self, hostname, username, password):

        client = ftplib.FTP()

        try:
            client.connect(host=hostname, port=self.port, timeout=self.timeout)
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e

        try:
            client.login(user=username, passwd=password)
        except ftplib.error_perm as e:
            raise AuthenticationFailure(str(e)) from e

        client.set_pasv(True)

        return client


    def _close(self):
        if self.client:
            self.client.quit()


    def _put(self, localfile, remotefile):
        # Try to create remote folder
        try:
            self.client.mkd(str(remotefile.parent))
        except ftplib.error_perm as e:
            # will return an error if the directory already exists
            #logger.warning('FTP error creating directory: %s', str(e))
            pass


        with io.open(str(localfile), 'rb') as f_localfile:
            try:
                self.client.storbinary('STOR {0}'.format(str(remotefile)), f_localfile, blocksize=262144)
            except ftplib.error_perm as e:
                f_localfile.close()
                raise TransferFailure(str(e)) from e

            f_localfile.close()


        try:
            self.client.sendcmd('SITE CHMOD 644 {0:s}'.format(str(remotefile)))
        except ftplib.error_perm as e:
            logger.warning('FTP unable to chmod file: %s', str(e))

