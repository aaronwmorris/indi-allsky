from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
import paramiko
import socket


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
        self.sftp.put(str(localfile), str(remotefile))

