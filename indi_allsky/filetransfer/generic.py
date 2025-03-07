#from pathlib import Path
import string
import random
import logging

logger = logging.getLogger('indi_allsky')


class GenericFileTransfer(object):
    def __init__(self, *args, **kwargs):
        self.config = args[0]
        self.delete = kwargs.get('delete', False)

        self._port = 0
        self._connect_timeout = 10.0
        self._timeout = 60.0
        self._atomic = False


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


    @property
    def connect_timeout(self):
        return self._connect_timeout

    @connect_timeout.setter
    def connect_timeout(self, new_connect_timeout):
        self._connect_timeout = float(new_connect_timeout)


    @property
    def atomic(self):
        return self._atomic

    @atomic.setter
    def atomic(self, new_atomic):
        self._atomic = bool(new_atomic)


    def connect(self, *args, **kwargs):
        #hostname = kwargs['hostname']
        #username = kwargs['username']
        #password = kwargs['password']

        #logger.info('Connecting to %s (%d) as %s with %s', hostname, self._port, username, self.__class__.__name__)

        pass


    def close(self):
        pass


    def put(self, *args, **kwargs):
        if self.delete:
            # perform delete instead of upload
            return self.delete()


        local_file = kwargs['local_file']
        logger.info('Uploading %s', local_file)


    def delete(self, *args, **kwargs):
        pass


    def tempname(self, suffix='.bin', size=8, chars=string.ascii_letters + string.digits):
        # generate random filename
        return 'tmp{0:s}{1:s}'.format(''.join(random.choice(chars) for _ in range(size)), suffix)  # suffix usually includes dot

