from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
import paramiko


class sftp(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(sftp, self).__init__(*args, **kwargs)

        self.port = 22
        self.transport = None


    def __del__(self):
        super(sftp, self).__del__()


    def _connect(self, hostname, username, password):

        self.transport = paramiko.Transport((hostname, self.port))

        try:
            self.transport.connect(None, username, password)
        except paramiko.ssh_exception.AuthenticationException as e:
            raise AuthenticationFailure(str(e)) from e

        client = paramiko.SFTPClient.from_transport(self.transport)
        #client.setTimeout(self.timeout)

        return client


    def _close(self):
        if self.transport:
            self.transport.close()

        if self.client:
            self.client.close()


    def _put(self, localfile, remotefile):
        self.client.put(localfile, remotefile)

