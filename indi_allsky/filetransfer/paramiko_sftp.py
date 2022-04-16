from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure

from pathlib import Path
import paramiko
import socket
import time
import logging

logger = logging.getLogger('indi_allsky')


class paramiko_sftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(paramiko_sftp, self).__init__(*args, **kwargs)

        self._port = 22
        self.sftp = None


    def connect(self, *args, **kwargs):
        super(paramiko_sftp, self).connect(*args, **kwargs)

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']


        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(hostname, port=self._port, username=username, password=password, timeout=self._timeout)
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


    def close(self):
        super(paramiko_sftp, self).close()

        if self.sftp:
            self.sftp.close()

        if self.client:
            self.client.close()


    def put(self, *args, **kwargs):
        super(paramiko_sftp, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        remote_file = kwargs['remote_file']

        local_file_p = Path(local_file)
        remote_file_p = Path(remote_file)

        # Try to create remote folder
        try:
            self.sftp.mkdir(str(remote_file_p.parent))
        except OSError as e:
            # will return an error if the directory already exists
            #logger.warning('SFTP error creating directory: %s', str(e))
            pass


        try:
            self.sftp.chmod(str(remote_file_p.parent), 0o755)
        except OSError as e:
            logger.warning('SFTP unable to chmod dir: %s', str(e))


        start = time.time()

        try:
            self.sftp.put(str(local_file_p), str(remote_file_p))
        except PermissionError as e:
            raise TransferFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)

        try:
            self.sftp.chmod(str(remote_file_p), 0o644)
        except OSError as e:
            logger.warning('SFTP unable to chmod file: %s', str(e))


