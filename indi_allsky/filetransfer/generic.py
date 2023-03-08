#from pathlib import Path
import logging

logger = logging.getLogger('indi_allsky')


class GenericFileTransfer(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]

        self._port = 0
        self._timeout = 5.0

        self._client = None


    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, new_port):
        self._port = int(new_port)


    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, new_timeout):
        self._timeout = float(new_timeout)


    def connect(self, *args, **kwargs):
        hostname = kwargs['hostname']
        username = kwargs['username']
        #password = kwargs['password']

        logger.info('Connecting to %s (%d) as %s with %s', hostname, self._port, username, self.__class__.__name__)


    def close(self):
        pass


    def put(self, *args, **kwargs):
        local_file = kwargs['local_file']

        logger.info('Uploading %s', local_file)

