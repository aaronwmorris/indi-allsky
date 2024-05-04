from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure

from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import socket
import time
import logging

logger = logging.getLogger('indi_allsky')


class libcloud_s3(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(libcloud_s3, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(libcloud_s3, self).connect(*args, **kwargs)

        from libcloud.storage.types import Provider
        from libcloud.storage.providers import get_driver


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
            timeout=self.timeout,
            secure=tls,
        )


    def close(self):
        super(libcloud_s3, self).close()


    def put(self, *args, **kwargs):
        super(libcloud_s3, self).put(*args, **kwargs)

        from libcloud.common.types import InvalidCredsError


        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        storage_class = kwargs['storage_class']
        acl = kwargs['acl']
        #metadata = kwargs['metadata']

        local_file_p = Path(local_file)


        container = self.client.get_container(container_name=bucket)

        extra_args = dict()


        # cache 30 days
        extra_args['cache_control'] = 'max-age=2592000'


        if local_file_p.suffix in ['.jpg', '.jpeg']:
            extra_args['content_type'] = 'image/jpeg'
        elif local_file_p.suffix in ['.mp4']:
            extra_args['content_type'] = 'video/mp4'
        elif local_file_p.suffix in ['.png']:
            extra_args['content_type'] = 'image/png'
        elif local_file_p.suffix in ['.webm']:
            extra_args['content_type'] = 'video/webm'
        elif local_file_p.suffix in ['.webp']:
            extra_args['content_type'] = 'image/webp'
        else:
            # default application/octet-stream
            pass


        if acl:
            extra_args['acl'] = acl  # all assets are normally publicly readable


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


    def delete(self, *args, **kwargs):
        super(libcloud_s3, self).delete(*args, **kwargs)

        from libcloud.common.types import InvalidCredsError

        bucket = kwargs['bucket']
        key = kwargs['key']

        container = self.client.get_container(container_name=bucket)


        try:
            obj = self.client.get_object(
                container,
                str(key),
            )

            self.client.delete_object(obj)
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except InvalidCredsError as e:
            raise AuthenticationFailure(str(e)) from e


        logger.info('S3 object deleted: %s', key)
