from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure
#from .exceptions import PermissionFailure

from pathlib import Path
import ftplib
import io
import socket
import time
import logging

logger = logging.getLogger('indi_allsky')


class python_ftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(python_ftp, self).__init__(*args, **kwargs)

        self.client = None
        self._port = 21


    def connect(self, *args, **kwargs):
        super(python_ftp, self).connect(*args, **kwargs)

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']
        #cert_bypass = kwargs.get('cert_bypass')


        self.client = ftplib.FTP()

        try:
            self.client.connect(host=hostname, port=self._port, timeout=self.timeout)
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e

        try:
            self.client.login(user=username, passwd=password)
        except ftplib.error_perm as e:
            raise AuthenticationFailure(str(e)) from e

        self.client.set_pasv(True)


    def close(self):
        super(python_ftp, self).close()

        if self.client:
            self.client.quit()


    def put(self, *args, **kwargs):
        super(python_ftp, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)


        # Try to create remote folder
        dir_list = list(remote_file_p.parents)
        dir_list.reverse()  # need root dirs first

        for d in dir_list:
            d_str = str(d)

            if d_str in ['.', '~', '/']:
                continue


            # Try to create remote folder
            try:
                self.client.mkd(d_str)
            except ftplib.error_perm as e:  # noqa: F841
                # will return an error if the directory already exists
                #logger.warning('FTP error creating directory: %s', str(e))
                pass


        start = time.time()

        try:
            with io.open(str(local_file_p), 'rb') as f_localfile:
                self.client.storbinary('STOR {0}'.format(str(remote_file_p)), f_localfile, blocksize=262144)
        except ftplib.error_perm as e:
            raise TransferFailure(str(e)) from e


        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        try:
            self.client.sendcmd('SITE CHMOD 644 {0:s}'.format(str(remote_file_p)))
        except ftplib.error_perm as e:
            logger.warning('FTP unable to chmod file: %s', str(e))

        try:
            self.client.sendcmd('SITE CHMOD 755 {0:s}'.format(str(remote_file_p.parent)))
        except ftplib.error_perm as e:
            logger.warning('FTP unable to chmod dir: %s', str(e))

