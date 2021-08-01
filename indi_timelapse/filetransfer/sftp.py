from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure

import paramiko
import socket
import time
import multiprocessing

logger = multiprocessing.get_logger()


class sftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(sftp, self).__init__(*args, **kwargs)

        self.port = 22
        self.sftp = None


    def __del__(self):
        super(sftp, self).__del__()


    def _connect(self, hostname, username, password):

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(hostname, port=self.port, username=username, password=password, timeout=self.timeout)
        except paramiko.ssh_exception.AuthenticationException as e:
            raise AuthenticationFailure(str(e)) from e
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            raise ConnectionFailure(str(e)) from e
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e

        self.sftp = client.open_sftp()

        return client


    def _close(self):
        if self.sftp:
            self.sftp.close()

        if self.client:
            self.client.close()


    def _put(self, localfile, remotefile):
        # Try to create remote folder
        try:
            self.sftp.mkdir(str(remotefile.parent))
        except OSError as e:
            # will return an error if the directory already exists
            #logger.warning('SFTP error creating directory: %s', str(e))
            pass


        start = time.time()

        try:
            self.sftp.put(str(localfile), str(remotefile))
        except PermissionError as e:
            raise TransferFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = localfile.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        try:
            self.sftp.chmod(str(remotefile), 0o644)
        except OSError as e:
            logger.warning('SFTP unable to chmod file: %s', str(e))


