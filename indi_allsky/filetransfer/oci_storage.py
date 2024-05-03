from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure

#import os
import io
from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import socket
import time
import requests.exceptions
import logging

logger = logging.getLogger('indi_allsky')


class oci_storage(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(oci_storage, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(oci_storage, self).connect(*args, **kwargs)

        import oci


        creds_file = kwargs['creds_file']
        #region = kwargs['region']
        #host = kwargs['hostname']  # endpoint_url
        #tls = kwargs['tls']
        #cert_bypass = kwargs['cert_bypass']


        #if cert_bypass:
        #    verify = False
        #else:
        #    verify = True


        config = oci.config.from_file(file_location=str(creds_file))

        self.client = oci.object_storage.ObjectStorageClient(
            config,
            timeout=(self.connect_timeout, self.timeout),
        )

        #namespace = self.client.get_namespace().data


    def close(self):
        super(oci_storage, self).close()


    def put(self, *args, **kwargs):
        super(oci_storage, self).put(*args, **kwargs)

        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        namespace = kwargs['namespace']
        #storage_class = kwargs['storage_class']
        #acl = kwargs['acl']
        #metadata = kwargs['metadata']

        local_file_p = Path(local_file)

        #extra_args = dict()

        # cache 90 days
        cache_control = 'public, max-age=7776000'


        if local_file_p.suffix in ['.jpg', '.jpeg']:
            content_type = 'image/jpeg'
        elif local_file_p.suffix in ['.mp4']:
            content_type = 'video/mp4'
        elif local_file_p.suffix in ['.png']:
            content_type = 'image/png'
        elif local_file_p.suffix in ['.webm']:
            content_type = 'video/webm'
        elif local_file_p.suffix in ['.webp']:
            content_type = 'image/webp'
        else:
            content_type = 'application/octet-stream'


        upload_kwargs = {
            'content_type'          : content_type,
            'cache_control'         : cache_control,
        }


        #if acl:
        #    upload_kwargs['predefined_acl'] = acl  # all assets are normally publicly readable


        start = time.time()

        try:
            with io.open(str(local_file_p), 'rb') as f_localfile:
                self.client.put_object(
                    namespace,
                    bucket,
                    str(key),
                    f_localfile,
                    **upload_kwargs,
                )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ReadTimeout as e:
            raise ConnectionFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


    def delete(self, *args, **kwargs):
        super(oci_storage, self).delete(*args, **kwargs)

        bucket = kwargs['bucket']
        key = kwargs['key']
        namespace = kwargs['namespace']


        try:
            self.client.delete_object(
                namespace,
                bucket,
                str(key),
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectTimeout as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except requests.exceptions.ReadTimeout as e:
            raise ConnectionFailure(str(e)) from e


        logger.info('S3 object deleted: %s', key)

