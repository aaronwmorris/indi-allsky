from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure

from pathlib import Path
import socket
import time
import logging

logger = logging.getLogger('indi_allsky')


class boto3_s3(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(boto3_s3, self).__init__(*args, **kwargs)

        self._port = 0


    def connect(self, *args, **kwargs):
        super(boto3_s3, self).connect(*args, **kwargs)




    def close(self):
        super(boto3_s3, self).close()


    def put(self, *args, **kwargs):
        super(boto3_s3, self).put(*args, **kwargs)

        local_file = kwargs['local_file']

        local_file_p = Path(local_file)



        start = time.time()

        try:
            pass
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


