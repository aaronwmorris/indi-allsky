import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.filetransfer.boto3_generic import boto3_generic
from indi_allsky.filetransfer.boto3_s3 import boto3_s3
from indi_allsky.filetransfer.boto3_minio import boto3_minio
from indi_allsky.filetransfer.requests_syncapi_v1 import requests_syncapi_v1
from indi_allsky.filetransfer.exceptions import ConnectionFailure, CertificateValidationFailure


def test_boto3_generic_connect_and_put(tmp_path):
    mock_boto3 = MagicMock()
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_boto3_exc = MagicMock()
    mock_boto3.exceptions = mock_boto3_exc

    mock_botocore = MagicMock()
    mock_botocore_client = MagicMock()
    mock_botocore_exceptions = MagicMock()
    mock_botocore.client = mock_botocore_client
    mock_botocore.exceptions = mock_botocore_exceptions

    with patch.dict(sys.modules, {
        'boto3': mock_boto3,
        'boto3.exceptions': mock_boto3_exc,
        'botocore': mock_botocore,
        'botocore.client': mock_botocore_client,
        'botocore.exceptions': mock_botocore_exceptions,
    }):
        transfer = boto3_generic({})
        transfer.connect(
            access_key='AKIAIOSFODNN7EXAMPLE',
            secret_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
            region='us-east-1',
            endpoint_url='https://s3.us-east-1.amazonaws.com',
            tls=True,
            cert_bypass=False,
        )

        test_file = tmp_path / "test.jpg"
        test_file.write_bytes(b"dummy image data")

        transfer.put(
            local_file=str(test_file),
            bucket='mybucket',
            key='images/test.jpg',
            storage_class='STANDARD',
            acl='public-read',
        )

        mock_client.upload_file.assert_called_once_with(
            str(test_file),
            'mybucket',
            'images/test.jpg',
            ExtraArgs={
                'ACL': 'public-read',
                'StorageClass': 'STANDARD',
                'ContentType': 'image/jpeg',
                'CacheControl': 'max-age=7776000',
            },
        )
        transfer.close()
        mock_client.close.assert_called_once()


def test_boto3_s3_and_minio_classes():
    s3_transfer = boto3_s3({})
    assert s3_transfer._port == 443

    minio_transfer = boto3_minio({})
    assert minio_transfer._port == 443


def test_requests_syncapi_v1(tmp_path):
    transfer = requests_syncapi_v1({})
    transfer.connect(
        hostname='https://sync.example.com/api/v1',
        username='node1',
        apikey='supersecretkey12345678901234567890',
        cert_bypass=True,
    )

    test_file = tmp_path / "sync_image.jpg"
    test_file.write_bytes(b"fake jpeg content")

    mock_resp = MagicMock(status_code=200, text='{"success": true}')
    with patch('requests.put', return_value=mock_resp) as mock_put:
        transfer.put(
            local_file=str(test_file),
            empty_file=False,
            metadata={'camera_uuid': 'cam-123', 'name': 'test'},
        )
        mock_put.assert_called_once()
        assert mock_put.call_args[1]['verify'] is False

    transfer.close()
