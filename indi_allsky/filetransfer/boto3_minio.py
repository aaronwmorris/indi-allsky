from .generic import GenericFileTransfer
#from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure

from pathlib import Path
#from datetime import datetime
#from datetime import timedelta
import socket
import time
import urllib3.exceptions
from urllib.parse import urlparse
import logging

logger = logging.getLogger('indi_allsky')


class boto3_minio(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(boto3_minio, self).__init__(*args, **kwargs)

        self._port = 443


    def connect(self, *args, **kwargs):
        super(boto3_minio, self).connect(*args, **kwargs)

        from botocore.client import Config
        import boto3


        access_key = kwargs['access_key']
        secret_key = kwargs['secret_key']
        region = kwargs['region']
        host = kwargs['hostname']
        bucket = kwargs['bucket']
        namespace = kwargs['namespace']
        template = kwargs['url_template']

        endpoint = template.format(
            host=host,
            bucket=bucket,
            region=region,
            namespace=namespace,
        )
        # Boto3 does not support having the bucket in the endpoint URL, it needs to be a base URL
        # However, the capture process sets s3_prefix with the bucket name included, so that the frontend
        # can use the same URL to access the files.
        # Therefore we must remove the path from the final templated url for boto3 to work
        parsed = urlparse(endpoint)
        endpoint = f'{parsed.scheme}://{parsed.netloc}'

        tls = kwargs['tls']
        cert_bypass = kwargs['cert_bypass']


        if cert_bypass:
            verify = False
        else:
            verify = True


        boto_config = Config(
            connect_timeout=self.connect_timeout,
            read_timeout=self.timeout,
            retries={'max_attempts': 0},
        )

        self.client = boto3.client(
            's3',
            region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint,
            use_ssl=tls,
            verify=verify,
            config=boto_config,
        )


    def close(self):
        super(boto3_minio, self).close()

        self.client.close()


    def put(self, *args, **kwargs):
        super(boto3_minio, self).put(*args, **kwargs)

        import botocore.exceptions
        import boto3.exceptions


        local_file = kwargs['local_file']
        bucket = kwargs['bucket']
        key = kwargs['key']
        storage_class = kwargs['storage_class']
        acl = kwargs['acl']
        #metadata = kwargs['metadata']

        local_file_p = Path(local_file)


        extra_args = dict()


        # cache 90 days
        extra_args['CacheControl'] = 'max-age=7776000'


        if local_file_p.suffix in ['.jpg', '.jpeg']:
            extra_args['ContentType'] = 'image/jpeg'
        elif local_file_p.suffix in ['.mp4']:
            extra_args['ContentType'] = 'video/mp4'
        elif local_file_p.suffix in ['.png']:
            extra_args['ContentType'] = 'image/png'
        elif local_file_p.suffix in ['.webm']:
            extra_args['ContentType'] = 'video/webm'
        elif local_file_p.suffix in ['.webp']:
            extra_args['ContentType'] = 'image/webp'
        else:
            # default application/octet-stream
            pass


        if acl:
            extra_args['ACL'] = acl  # all assets are normally publicly readable


        if storage_class:
            extra_args['StorageClass'] = storage_class


        start = time.time()

        try:
            self.client.upload_file(
                str(local_file_p),
                bucket,
                str(key),
                ExtraArgs=extra_args,
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.ConnectTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except urllib3.exceptions.ReadTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except urllib3.exceptions.NewConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.ReadTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.EndpointConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except boto3.exceptions.S3UploadFailedError as e:
            raise TransferFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


    def delete(self, *args, **kwargs):
        super(boto3_minio, self).delete(*args, **kwargs)

        import botocore.exceptions
        import boto3.exceptions


        bucket = kwargs['bucket']
        key = kwargs['key']

        try:
            self.client.delete_object(
                Bucket=bucket,
                Key=str(key),
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.ConnectTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except urllib3.exceptions.ReadTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except urllib3.exceptions.NewConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.ReadTimeoutError as e:
            raise ConnectionFailure(str(e)) from e
        except botocore.exceptions.EndpointConnectionError as e:
            raise ConnectionFailure(str(e)) from e
        except boto3.exceptions.S3UploadFailedError as e:
            raise TransferFailure(str(e)) from e


        logger.info('S3 object deleted: %s', key)

