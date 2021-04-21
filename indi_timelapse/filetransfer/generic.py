from .exceptions import AuthenticationFailure

class GenericFileTransfer(object):
    def __init__(self, timeout=5.0):
        self.timeout = timeout

        self.port = 0
        self.client = None


    def __del__(self):
        pass


    def connect(self, hostname, username, password, port=None):
        if port:
            self.port = port

        self.client = self._connect(hostname, username, password)


    def close(self):
        self._close()


    def put(self, localfile, remotefile):
        self._put(localfile, remotefile)

