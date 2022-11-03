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

        self.client = None
        self._port = 22
        self.sftp = None


    def connect(self, *args, **kwargs):
        super(paramiko_sftp, self).connect(*args, **kwargs)

        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs['password']
        cert_bypass = kwargs.get('cert_bypass')
        private_key = kwargs.get('private_key')


        self.client = paramiko.SSHClient()


        if cert_bypass:
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())


        connect_kwargs = {
            'port'      : self._port,
            'username'  : username,
            'timeout'   : self._timeout,
        }


        if private_key:
            # ssh key auth
            connect_kwargs['key_filename'] = private_key

            if password:
                connect_kwargs['passphrase'] = password  # key passphrase
        else:
            # password auth
            connect_kwargs['password'] = password


        try:
            self.client.connect(hostname, **connect_kwargs)
        except paramiko.ssh_exception.AuthenticationException as e:
            raise AuthenticationFailure(str(e)) from e
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            raise ConnectionFailure(str(e)) from e
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e

        self.sftp = self.client.open_sftp()


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


        if str(remote_file_p).startswith('~'):
            logger.warning('paramiko does not support ~ for remote file paths')


        # Try to create remote folder
        dir_list = list(remote_file_p.parents)
        dir_list.reverse()  # need root dirs first

        for d in dir_list:
            d_str = str(d)

            if d_str in ['.', '~', '/']:
                continue

            try:
                self.sftp.mkdir(d_str)
            except OSError as e:  # noqa: F841
                # will return an error if the directory already exists
                #logger.warning('SFTP error creating directory: %s', str(e))
                pass


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

        try:
            self.sftp.chmod(str(remote_file_p.parent), 0o755)
        except OSError as e:
            logger.warning('SFTP unable to chmod dir: %s', str(e))

