import io
import sys
import socket
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import botocore.exceptions
import boto3.exceptions
import urllib3.exceptions
import requests.exceptions

from indi_allsky.filetransfer.boto3_generic import boto3_generic
from indi_allsky.filetransfer.boto3_s3 import boto3_s3
from indi_allsky.filetransfer.boto3_minio import boto3_minio
from indi_allsky.filetransfer.requests_syncapi_v1 import requests_syncapi_v1
from indi_allsky.filetransfer.gcp_storage import gcp_storage
from indi_allsky.filetransfer.libcloud_s3 import libcloud_s3
from indi_allsky.filetransfer.oci_storage import oci_storage
from indi_allsky.filetransfer.exceptions import (
    ConnectionFailure,
    CertificateValidationFailure,
    AuthenticationFailure,
    TransferFailure,
)


def test_boto3_generic_lifecycle_and_content_types(tmp_path):
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_generic({})
        assert transfer._port == 443

        # Connect with cert_bypass=True
        transfer.connect(
            access_key='key_bypass',
            secret_key='sec_bypass',
            region='us-west-2',
            endpoint_url='https://custom.endpoint',
            tls=False,
            cert_bypass=True,
        )
        assert mock_boto3.client.call_args[1]['verify'] is False
        assert mock_boto3.client.call_args[1]['use_ssl'] is False

        # Connect with cert_bypass=False
        transfer.connect(
            access_key='AKIAIOSFODNN7EXAMPLE',
            secret_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
            region='us-east-1',
            endpoint_url='https://s3.us-east-1.amazonaws.com',
            tls=True,
            cert_bypass=False,
        )
        assert mock_boto3.client.call_args[1]['verify'] is True
        assert mock_boto3.client.call_args[1]['use_ssl'] is True

        # Test content types in put()
        extensions_map = [
            ('img.jpg', 'image/jpeg'),
            ('img.jpeg', 'image/jpeg'),
            ('video.mp4', 'video/mp4'),
            ('img.png', 'image/png'),
            ('video.webm', 'video/webm'),
            ('img.webp', 'image/webp'),
            ('data.bin', None),
        ]
        for filename, expected_content_type in extensions_map:
            f = tmp_path / filename
            f.write_bytes(b'dummy data')
            transfer.put(
                local_file=str(f),
                bucket='mybucket',
                key=f'uploads/{filename}',
                storage_class='STANDARD',
                acl='public-read',
            )
            extra_args = mock_client.upload_file.call_args[1]['ExtraArgs']
            assert extra_args['CacheControl'] == 'max-age=7776000'
            assert extra_args['ACL'] == 'public-read'
            assert extra_args['StorageClass'] == 'STANDARD'
            if expected_content_type:
                assert extra_args['ContentType'] == expected_content_type
            else:
                assert 'ContentType' not in extra_args

        # Test delete
        transfer.delete(bucket='mybucket', key='uploads/img.jpg')
        mock_client.delete_object.assert_called_with(Bucket='mybucket', Key='uploads/img.jpg')

        # Test close
        transfer.close()
        mock_client.close.assert_called()


@pytest.mark.parametrize('raised_exc, expected_wrapped', [
    (socket.gaierror('dns fail'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
    (ConnectionRefusedError('refused'), ConnectionFailure),
    (ssl.SSLEOFError('ssl eof'), CertificateValidationFailure),
    (botocore.exceptions.ConnectTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (urllib3.exceptions.ReadTimeoutError(None, 'http://x', 'timeout'), ConnectionFailure),
    (urllib3.exceptions.NewConnectionError(None, 'failed'), ConnectionFailure),
    (urllib3.exceptions.ProtocolError('proto'), ConnectionFailure),
    (urllib3.exceptions.SSLError('ssl'), CertificateValidationFailure),
    (botocore.exceptions.ReadTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.EndpointConnectionError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.ConnectionClosedError(endpoint_url='http://x'), ConnectionFailure),
    (boto3.exceptions.S3UploadFailedError('failed'), TransferFailure),
    (botocore.exceptions.SSLError(endpoint_url='http://x', error='ssl error'), CertificateValidationFailure),
])
def test_boto3_generic_exceptions(tmp_path, raised_exc, expected_wrapped):
    mock_boto3 = MagicMock()
    mock_boto3.exceptions = boto3.exceptions
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_generic({})
        transfer.connect(
            access_key='k', secret_key='s', region='r', endpoint_url='https://s3.local',
            tls=True, cert_bypass=False
        )
        f = tmp_path / "test.jpg"
        f.write_bytes(b'x')

        # put() error
        mock_client.upload_file.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.put(
                local_file=str(f),
                bucket='b',
                key='k',
                storage_class=None,
                acl=None,
            )

        # delete() error
        mock_client.delete_object.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.delete(bucket='b', key='k')


def test_boto3_s3_lifecycle_and_content_types(tmp_path):
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_s3({'FILETRANSFER': {}})
        assert transfer._port == 443

        # Connect with cert_bypass=False
        transfer.connect(
            access_key='key',
            secret_key='sec',
            region='us-east-1',
            tls=True,
            cert_bypass=False,
        )
        mock_boto3.client.assert_called_with(
            's3',
            'us-east-1',
            aws_access_key_id='key',
            aws_secret_access_key='sec',
            use_ssl=True,
            verify=True,
            config=mock_boto3.client.call_args[1]['config'],
        )

        # Connect with cert_bypass=True
        transfer.connect(
            access_key='key2',
            secret_key='sec2',
            region='eu-west-1',
            tls=False,
            cert_bypass=True,
        )
        assert mock_boto3.client.call_args[1]['verify'] is False

        # Test various content types in put()
        extensions_map = [
            ('img.jpg', 'image/jpeg'),
            ('img.jpeg', 'image/jpeg'),
            ('video.mp4', 'video/mp4'),
            ('img.png', 'image/png'),
            ('video.webm', 'video/webm'),
            ('img.webp', 'image/webp'),
            ('data.bin', None),
        ]
        for filename, expected_content_type in extensions_map:
            f = tmp_path / filename
            f.write_bytes(b'x')
            transfer.put(
                local_file=str(f),
                bucket='mybucket',
                key=filename,
                storage_class='INTELLIGENT_TIERING',
                acl='public-read',
            )
            extra_args = mock_client.upload_file.call_args[1]['ExtraArgs']
            assert extra_args['CacheControl'] == 'max-age=7776000'
            assert extra_args['ACL'] == 'public-read'
            assert extra_args['StorageClass'] == 'INTELLIGENT_TIERING'
            if expected_content_type:
                assert extra_args['ContentType'] == expected_content_type
            else:
                assert 'ContentType' not in extra_args

        # Test delete
        transfer.delete(bucket='mybucket', key='del.jpg')
        mock_client.delete_object.assert_called_with(Bucket='mybucket', Key='del.jpg')

        # Test close
        transfer.close()
        mock_client.close.assert_called()


@pytest.mark.parametrize('raised_exc, expected_wrapped', [
    (socket.gaierror('dns fail'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
    (ConnectionRefusedError('refused'), ConnectionFailure),
    (ssl.SSLEOFError('ssl eof'), CertificateValidationFailure),
    (botocore.exceptions.ConnectTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (urllib3.exceptions.ReadTimeoutError(None, 'http://x', 'timeout'), ConnectionFailure),
    (urllib3.exceptions.NewConnectionError(None, 'failed'), ConnectionFailure),
    (urllib3.exceptions.ProtocolError('proto'), ConnectionFailure),
    (urllib3.exceptions.SSLError('ssl'), CertificateValidationFailure),
    (botocore.exceptions.ReadTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.EndpointConnectionError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.ConnectionClosedError(endpoint_url='http://x'), ConnectionFailure),
    (boto3.exceptions.S3UploadFailedError('failed'), TransferFailure),
    (botocore.exceptions.SSLError(endpoint_url='http://x', error='ssl error'), CertificateValidationFailure),
])
def test_boto3_s3_exceptions(tmp_path, raised_exc, expected_wrapped):
    mock_boto3 = MagicMock()
    mock_boto3.exceptions = boto3.exceptions
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_s3({})
        transfer.connect(
            access_key='k', secret_key='s', region='r', tls=True, cert_bypass=False
        )
        f = tmp_path / "test.jpg"
        f.write_bytes(b'x')

        # put() error
        mock_client.upload_file.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.put(
                local_file=str(f),
                bucket='b',
                key='k',
                storage_class=None,
                acl=None,
            )

        # delete() error
        mock_client.delete_object.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.delete(bucket='b', key='k')


def test_boto3_minio_lifecycle_and_content_types(tmp_path):
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_minio({'FILETRANSFER': {}})
        assert transfer._port == 443

        transfer.connect(
            access_key='access',
            secret_key='secret',
            region='us-east-1',
            hostname='play.min.io:9000',
            bucket='mybucket',
            namespace='default',
            url_template='https://{host}/{bucket}/{namespace}',
            tls=True,
            cert_bypass=False,
        )
        assert mock_boto3.client.call_args[1]['endpoint_url'] == 'https://play.min.io:9000'
        assert mock_boto3.client.call_args[1]['verify'] is True

        transfer.connect(
            access_key='access',
            secret_key='secret',
            region='us-east-1',
            hostname='localhost:9000',
            bucket='mybucket',
            namespace='default',
            url_template='http://{host}/{bucket}',
            tls=False,
            cert_bypass=True,
        )
        assert mock_boto3.client.call_args[1]['endpoint_url'] == 'http://localhost:9000'
        assert mock_boto3.client.call_args[1]['verify'] is False

        # Put with types
        for filename, expected_content_type in [
            ('img.jpg', 'image/jpeg'),
            ('img.jpeg', 'image/jpeg'),
            ('video.mp4', 'video/mp4'),
            ('img.png', 'image/png'),
            ('video.webm', 'video/webm'),
            ('img.webp', 'image/webp'),
            ('data.bin', None),
        ]:
            f = tmp_path / filename
            f.write_bytes(b'abc')
            transfer.put(
                local_file=str(f),
                bucket='mybucket',
                key=filename,
                storage_class='STANDARD',
                acl='public-read',
            )
            extra_args = mock_client.upload_file.call_args[1]['ExtraArgs']
            assert extra_args['CacheControl'] == 'max-age=7776000'
            assert extra_args['ACL'] == 'public-read'
            assert extra_args['StorageClass'] == 'STANDARD'
            if expected_content_type:
                assert extra_args['ContentType'] == expected_content_type
            else:
                assert 'ContentType' not in extra_args

        # Delete
        transfer.delete(bucket='mybucket', key='test.jpg')
        mock_client.delete_object.assert_called_with(Bucket='mybucket', Key='test.jpg')

        # Close
        transfer.close()
        mock_client.close.assert_called()


@pytest.mark.parametrize('raised_exc, expected_wrapped', [
    (socket.gaierror('dns fail'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
    (ConnectionRefusedError('refused'), ConnectionFailure),
    (ssl.SSLEOFError('ssl eof'), CertificateValidationFailure),
    (botocore.exceptions.ConnectTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (urllib3.exceptions.ReadTimeoutError(None, 'http://x', 'timeout'), ConnectionFailure),
    (urllib3.exceptions.NewConnectionError(None, 'failed'), ConnectionFailure),
    (urllib3.exceptions.ProtocolError('proto'), ConnectionFailure),
    (urllib3.exceptions.SSLError('ssl'), CertificateValidationFailure),
    (botocore.exceptions.ReadTimeoutError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.EndpointConnectionError(endpoint_url='http://x'), ConnectionFailure),
    (botocore.exceptions.ConnectionClosedError(endpoint_url='http://x'), ConnectionFailure),
    (boto3.exceptions.S3UploadFailedError('failed'), TransferFailure),
    (botocore.exceptions.SSLError(endpoint_url='http://x', error='ssl error'), CertificateValidationFailure),
])
def test_boto3_minio_exceptions(tmp_path, raised_exc, expected_wrapped):
    mock_boto3 = MagicMock()
    mock_boto3.exceptions = boto3.exceptions
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict(sys.modules, {'boto3': mock_boto3}):
        transfer = boto3_minio({})
        transfer.connect(
            access_key='k', secret_key='s', region='r', hostname='minio.local',
            bucket='b', namespace='ns', url_template='https://{host}/{bucket}',
            tls=True, cert_bypass=False
        )
        f = tmp_path / "test.jpg"
        f.write_bytes(b'x')

        # put() error
        mock_client.upload_file.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.put(
                local_file=str(f),
                bucket='b',
                key='k',
                storage_class=None,
                acl=None,
            )

        # delete() error
        mock_client.delete_object.side_effect = raised_exc
        with pytest.raises(expected_wrapped):
            transfer.delete(bucket='b', key='k')


def test_requests_syncapi_v1_modes(tmp_path):
    transfer = requests_syncapi_v1({})
    # Test cert_bypass=False
    transfer.connect(
        hostname='https://sync.example.com/api/v1',
        username='node1',
        apikey='supersecretkey12345678901234567890',
        cert_bypass=False,
    )
    assert transfer.verify is True

    # Test cert_bypass=True
    transfer.connect(
        hostname='https://sync.example.com/api/v1',
        username='node1',
        apikey='supersecretkey12345678901234567890',
        cert_bypass=True,
    )
    assert transfer.verify is False

    test_file = tmp_path / "sync_image.jpg"
    test_file.write_bytes(b"fake jpeg content")

    mock_resp = MagicMock(status_code=200, text='{"success": true}')
    with patch('requests.put', return_value=mock_resp) as mock_put:
        # Standard put
        meta = {'camera_uuid': 'cam-123', 'name': 'test'}
        res = transfer.put(
            local_file=str(test_file),
            empty_file=False,
            metadata=meta,
        )
        assert res == {"success": True}
        assert meta['file_size'] == len(b"fake jpeg content")
        assert mock_put.call_args[1]['verify'] is False

        # Camera put
        meta_cam = {'camera_uuid': 'cam-123'}
        res_cam = transfer.put(
            local_file='camera',
            empty_file=False,
            metadata=meta_cam,
        )
        assert res_cam == {"success": True}
        assert meta_cam['file_size'] == 0

        # Empty file put
        meta_empty = {'camera_uuid': 'cam-123'}
        res_empty = transfer.put(
            local_file=str(test_file),
            empty_file=True,
            metadata=meta_empty,
        )
        assert res_empty == {"success": True}
        assert meta_empty['file_size'] == 0

    transfer.close()


def test_requests_syncapi_v1_status_error(tmp_path):
    transfer = requests_syncapi_v1({})
    transfer.connect(
        hostname='https://sync.example.com/api/v1',
        username='node1',
        apikey='supersecretkey12345678901234567890',
        cert_bypass=True,
    )

    test_file = tmp_path / "sync_image.jpg"
    test_file.write_bytes(b"fake jpeg content")

    mock_resp = MagicMock(status_code=400, text='{"error": "bad request"}')
    with patch('requests.put', return_value=mock_resp):
        with pytest.raises(TransferFailure, match='Sync error: 400'):
            transfer.put(
                local_file=str(test_file),
                empty_file=False,
                metadata={},
            )


@pytest.mark.parametrize('raised_exc, expected_wrapped', [
    (socket.gaierror('dns error'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
    (requests.exceptions.ConnectTimeout('connect timeout'), ConnectionFailure),
    (requests.exceptions.ConnectionError('connection error'), ConnectionFailure),
    (requests.exceptions.ReadTimeout('read timeout'), ConnectionFailure),
    (ssl.SSLCertVerificationError('ssl verification failed'), CertificateValidationFailure),
    (requests.exceptions.SSLError('ssl error'), CertificateValidationFailure),
])
def test_requests_syncapi_v1_exceptions(tmp_path, raised_exc, expected_wrapped):
    transfer = requests_syncapi_v1({})
    transfer.connect(
        hostname='https://sync.example.com/api/v1',
        username='node1',
        apikey='supersecretkey12345678901234567890',
        cert_bypass=True,
    )

    test_file = tmp_path / "sync_image.jpg"
    test_file.write_bytes(b"fake jpeg content")

    with patch('requests.put', side_effect=raised_exc):
        with pytest.raises(expected_wrapped):
            transfer.put(
                local_file=str(test_file),
                empty_file=False,
                metadata={},
            )


class MockGcpNotFound(Exception):
    pass


class MockLibcloudInvalidCredsError(Exception):
    pass


def test_gcp_storage_lifecycle_and_content_types(tmp_path):
    mock_google = MagicMock()
    mock_cloud = MagicMock()
    mock_storage = MagicMock()
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_cloud.storage = mock_storage
    mock_storage.Client.return_value = mock_client
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    mock_api_core = MagicMock()
    mock_api_core.exceptions.NotFound = MockGcpNotFound
    mock_google.cloud = mock_cloud
    mock_google.api_core = mock_api_core

    with patch.dict(sys.modules, {
        'google': mock_google,
        'google.cloud': mock_cloud,
        'google.cloud.storage': mock_storage,
        'google.api_core': mock_api_core,
        'google.api_core.exceptions': mock_api_core.exceptions,
    }):
        transfer = gcp_storage({'FILETRANSFER': {}})
        assert transfer._port == 443

        transfer.connect(creds_file='/path/to/creds.json')
        assert transfer.client is mock_client
        transfer.close()

        # Test content types
        ext_to_content_type = {
            'image.jpg': 'image/jpeg',
            'video.mp4': 'video/mp4',
            'chart.png': 'image/png',
            'clip.webm': 'video/webm',
            'preview.webp': 'image/webp',
            'data.bin': 'application/octet-stream',
        }

        for filename, expected_ct in ext_to_content_type.items():
            f = tmp_path / filename
            f.write_bytes(b'filecontent')
            transfer.put(
                local_file=str(f),
                bucket='my-gcp-bucket',
                key=f'uploads/{filename}',
                acl='public-read',
            )
            assert mock_blob.upload_from_filename.call_args[1]['content_type'] == expected_ct
            assert mock_blob.upload_from_filename.call_args[1]['predefined_acl'] == 'public-read'

        # Test delete
        transfer.delete(bucket='my-gcp-bucket', key='uploads/image.jpg')
        mock_blob.delete.assert_called()

        # Test delete not found (should catch gracefully)
        mock_blob.delete.side_effect = MockGcpNotFound('not found')
        transfer.delete(bucket='my-gcp-bucket', key='uploads/image.jpg')


@pytest.mark.parametrize('raised_exc', [
    socket.gaierror('dns error'),
    socket.timeout('timed out'),
    ConnectionRefusedError('refused'),
    requests.exceptions.ConnectTimeout('connect timeout'),
    requests.exceptions.ConnectionError('connection error'),
    requests.exceptions.ReadTimeout('read timeout'),
])
def test_gcp_storage_exceptions(tmp_path, raised_exc):
    mock_google = MagicMock()
    mock_cloud = MagicMock()
    mock_storage = MagicMock()
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_cloud.storage = mock_storage
    mock_storage.Client.return_value = mock_client
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    mock_api_core = MagicMock()
    mock_api_core.exceptions.NotFound = MockGcpNotFound
    mock_google.cloud = mock_cloud
    mock_google.api_core = mock_api_core

    with patch.dict(sys.modules, {
        'google': mock_google,
        'google.cloud': mock_cloud,
        'google.cloud.storage': mock_storage,
        'google.api_core': mock_api_core,
        'google.api_core.exceptions': mock_api_core.exceptions,
    }):
        transfer = gcp_storage({'FILETRANSFER': {}})
        transfer.connect(creds_file='/path/to/creds.json')
        f = tmp_path / "img.jpg"
        f.write_bytes(b'data')

        mock_blob.upload_from_filename.side_effect = raised_exc
        with pytest.raises(ConnectionFailure):
            transfer.put(local_file=str(f), bucket='b', key='k', acl=None)

        mock_blob.delete.side_effect = raised_exc
        with pytest.raises(ConnectionFailure):
            transfer.delete(bucket='b', key='k')


def test_libcloud_s3_lifecycle_and_content_types(tmp_path):
    mock_driver_cls = MagicMock()
    mock_driver_instance = MagicMock()
    mock_driver_cls.return_value = mock_driver_instance
    mock_container = MagicMock()
    mock_driver_instance.get_container.return_value = mock_container

    mock_libcloud = MagicMock()
    mock_libcloud.storage.types.Provider.S3 = 's3'
    mock_libcloud.storage.providers.get_driver.return_value = mock_driver_cls
    mock_libcloud.common.types.InvalidCredsError = MockLibcloudInvalidCredsError

    with patch.dict(sys.modules, {
        'libcloud': mock_libcloud,
        'libcloud.storage': mock_libcloud.storage,
        'libcloud.storage.types': mock_libcloud.storage.types,
        'libcloud.storage.providers': mock_libcloud.storage.providers,
        'libcloud.common': mock_libcloud.common,
        'libcloud.common.types': mock_libcloud.common.types,
    }):
        transfer = libcloud_s3({'FILETRANSFER': {}})
        assert transfer._port == 443

        transfer.connect(
            access_key='key',
            secret_key='secret',
            region='us-east-1',
            tls=True,
        )
        assert transfer.client is mock_driver_instance
        transfer.close()

        ext_to_content_type = {
            'image.jpg': 'image/jpeg',
            'video.mp4': 'video/mp4',
            'chart.png': 'image/png',
            'clip.webm': 'video/webm',
            'preview.webp': 'image/webp',
            'data.bin': None,
        }

        for filename, expected_ct in ext_to_content_type.items():
            f = tmp_path / filename
            f.write_bytes(b'data')
            transfer.put(
                local_file=str(f),
                bucket='mybucket',
                key=f'k/{filename}',
                storage_class='STANDARD',
                acl='public-read',
            )
            extra_passed = mock_driver_instance.upload_object.call_args[1]['extra']
            if expected_ct:
                assert extra_passed['content_type'] == expected_ct
            else:
                assert 'content_type' not in extra_passed
            assert extra_passed['acl'] == 'public-read'

        # Test delete
        mock_obj = MagicMock()
        mock_driver_instance.get_object.return_value = mock_obj
        transfer.delete(bucket='mybucket', key='k/image.jpg')
        mock_driver_instance.delete_object.assert_called_with(mock_obj)


@pytest.mark.parametrize('raised_exc, expected_exc', [
    (socket.gaierror('dns error'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
    (ConnectionRefusedError('refused'), ConnectionFailure),
    (MockLibcloudInvalidCredsError('invalid creds'), AuthenticationFailure),
])
def test_libcloud_s3_exceptions(tmp_path, raised_exc, expected_exc):
    mock_driver_cls = MagicMock()
    mock_driver_instance = MagicMock()
    mock_driver_cls.return_value = mock_driver_instance

    mock_libcloud = MagicMock()
    mock_libcloud.storage.types.Provider.S3 = 's3'
    mock_libcloud.storage.providers.get_driver.return_value = mock_driver_cls
    mock_libcloud.common.types.InvalidCredsError = MockLibcloudInvalidCredsError

    with patch.dict(sys.modules, {
        'libcloud': mock_libcloud,
        'libcloud.storage': mock_libcloud.storage,
        'libcloud.storage.types': mock_libcloud.storage.types,
        'libcloud.storage.providers': mock_libcloud.storage.providers,
        'libcloud.common': mock_libcloud.common,
        'libcloud.common.types': mock_libcloud.common.types,
    }):
        transfer = libcloud_s3({'FILETRANSFER': {}})
        transfer.connect(access_key='k', secret_key='s', region='r', tls=True)

        f = tmp_path / "img.jpg"
        f.write_bytes(b'data')

        mock_driver_instance.get_container.return_value = MagicMock()
        mock_driver_instance.upload_object.side_effect = raised_exc

        with pytest.raises(expected_exc):
            transfer.put(local_file=str(f), bucket='b', key='k', storage_class='STANDARD', acl=None)

        mock_driver_instance.get_object.side_effect = raised_exc
        with pytest.raises(expected_exc):
            transfer.delete(bucket='b', key='k')


def test_oci_storage_lifecycle_and_content_types(tmp_path):
    mock_oci = MagicMock()
    mock_client = MagicMock()
    mock_oci.object_storage.ObjectStorageClient.return_value = mock_client
    mock_oci.config.from_file.return_value = {'user': 'user1'}

    with patch.dict(sys.modules, {'oci': mock_oci, 'oci.config': mock_oci.config, 'oci.object_storage': mock_oci.object_storage}):
        transfer = oci_storage({'FILETRANSFER': {}})
        assert transfer._port == 443

        transfer.connect(creds_file='/path/to/oci.config')
        assert transfer.client is mock_client
        transfer.close()

        ext_to_content_type = {
            'image.jpg': 'image/jpeg',
            'video.mp4': 'video/mp4',
            'chart.png': 'image/png',
            'clip.webm': 'video/webm',
            'preview.webp': 'image/webp',
            'data.bin': 'application/octet-stream',
        }

        for filename, expected_ct in ext_to_content_type.items():
            f = tmp_path / filename
            f.write_bytes(b'data')
            transfer.put(
                local_file=str(f),
                bucket='my-oci-bucket',
                key=f'k/{filename}',
                namespace='my-ns',
            )
            assert mock_client.put_object.call_args[1]['content_type'] == expected_ct
            assert mock_client.put_object.call_args[1]['cache_control'] == 'public, max-age=7776000'

        # Test delete
        transfer.delete(bucket='my-oci-bucket', key='k/image.jpg', namespace='my-ns')
        mock_client.delete_object.assert_called_with('my-ns', 'my-oci-bucket', 'k/image.jpg')


@pytest.mark.parametrize('raised_exc', [
    socket.gaierror('dns error'),
    socket.timeout('timed out'),
    ConnectionRefusedError('refused'),
    requests.exceptions.ConnectTimeout('connect timeout'),
    requests.exceptions.ConnectionError('connection error'),
    requests.exceptions.ReadTimeout('read timeout'),
])
def test_oci_storage_exceptions(tmp_path, raised_exc):
    mock_oci = MagicMock()
    mock_client = MagicMock()
    mock_oci.object_storage.ObjectStorageClient.return_value = mock_client
    mock_oci.config.from_file.return_value = {'user': 'user1'}

    with patch.dict(sys.modules, {'oci': mock_oci, 'oci.config': mock_oci.config, 'oci.object_storage': mock_oci.object_storage}):
        transfer = oci_storage({'FILETRANSFER': {}})
        transfer.connect(creds_file='/path/to/oci.config')

        f = tmp_path / "img.jpg"
        f.write_bytes(b'data')

        mock_client.put_object.side_effect = raised_exc
        with pytest.raises(ConnectionFailure):
            transfer.put(local_file=str(f), bucket='b', key='k', namespace='ns')

        mock_client.delete_object.side_effect = raised_exc
        with pytest.raises(ConnectionFailure):
            transfer.delete(bucket='b', key='k', namespace='ns')


