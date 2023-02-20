from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure

from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import socket
import time
from libcloud.storage.types import Provider
from libcloud.storage.providers import get_driver
from libcloud.common.types import InvalidCredsError
import logging

logger = logging.getLogger('indi_allsky')


class libcloud_s3(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(libcloud_s3, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(libcloud_s3, self).connect(*args, **kwargs)

        access_key = kwargs['access_key']
        secret_key = kwargs['secret_key']
        region = kwargs['region']
        #host = kwargs['hostname']  # endpoint_url
        tls = kwargs['tls']
        #cert_bypass = kwargs['cert_bypass']


        driver = get_driver(Provider.S3)

        self.client = driver(
            access_key,
            secret=secret_key,
            region=region,
            timeout=self._timeout,
            secure=tls,
        )


    def close(self):
        super(libcloud_s3, self).close()


    def put(self, *args, **kwargs):
        super(libcloud_s3, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        storage_class = kwargs['storage_class']
        #expire_days = kwargs['expire_days']
        acl = kwargs['acl']

        local_file_p = Path(local_file)


        container = self.client.get_container(container_name=bucket)

        extra_args = dict()

        if acl:
            extra_args['acl'] = acl  # all assets are normally publicly readable


        #if expire_days:
        #    now = datetime.now()
        #    extra_args['Expires'] = now + timedelta(days=expire_days)


        start = time.time()

        try:
            self.client.upload_object(
                str(local_file_p),
                container,
                str(key),
                ex_storage_class=storage_class.lower(),  # expects lower case keys
                extra=extra_args,
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except InvalidCredsError as e:
            raise AuthenticationFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


