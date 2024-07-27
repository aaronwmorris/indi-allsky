from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
#from .exceptions import TransferFailure

import os
from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import socket
import time
import requests.exceptions
import logging

logger = logging.getLogger('indi_allsky')


class gcp_storage(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(gcp_storage, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(gcp_storage, self).connect(*args, **kwargs)

        from google.cloud import storage
        #from google.api_core.client_options import ClientOptions


        creds_file = kwargs['creds_file']
        #region = kwargs['region']
        #host = kwargs['hostname']  # endpoint_url
        #tls = kwargs['tls']
        #cert_bypass = kwargs['cert_bypass']


        #if cert_bypass:
        #    verify = False
        #else:
        #    verify = True


        # not sure why this is not working
        #options = ClientOptions(
        #    credentials_file=str(creds_file),
        #)

        #self.client = storage.Client(
        #    client_options=options,
        #)


        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(creds_file)

        self.client = storage.Client()


    def close(self):
        super(gcp_storage, self).close()


    def put(self, *args, **kwargs):
        super(gcp_storage, self).put(*args, **kwargs)


        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        #storage_class = kwargs['storage_class']
        acl = kwargs['acl']
        #metadata = kwargs['metadata']

        local_file_p = Path(local_file)


        gcp_bucket = self.client.bucket(bucket)
        blob = gcp_bucket.blob(key)


        #extra_args = dict()

        # cache 90 days
        blob.cache_control = 'public, max-age=7776000'


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
            #'if_generation_match'   : 0,  # 0 does not allow overwriting existing uploads
            'content_type'          : content_type,
            'timeout'               : (self.connect_timeout, self.timeout),
            'retry'                 : None,
        }


        if acl:
            upload_kwargs['predefined_acl'] = acl  # all assets are normally publicly readable


        start = time.time()

        try:
            blob.upload_from_filename(
                str(local_file_p),
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
        super(gcp_storage, self).delete(*args, **kwargs)

        import google.api_core.exceptions


        # delete file
        bucket = kwargs['bucket']
        key = kwargs['key']


        gcp_bucket = self.client.bucket(bucket)
        blob = gcp_bucket.blob(key)


        delete_kwargs = {
            'timeout'               : (self.connect_timeout, self.timeout),
            'retry'                 : None,
        }


        try:
            blob.delete(
                **delete_kwargs,
            )
        except google.api_core.exceptions.NotFound:
            logger.error('S3 file not found')
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

