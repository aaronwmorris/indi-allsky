import pytest

from indi_allsky.filetransfer.generic import GenericFileTransfer
from indi_allsky.filetransfer.exceptions import (
    AuthenticationFailure,
    ConnectionFailure,
    TransferFailure,
    PermissionFailure,
    CertificateValidationFailure,
)


def test_filetransfer_exceptions():
    with pytest.raises(AuthenticationFailure):
        raise AuthenticationFailure("Auth failed")

    with pytest.raises(ConnectionFailure):
        raise ConnectionFailure("Connect failed")

    with pytest.raises(TransferFailure):
        raise TransferFailure("Transfer failed")

    with pytest.raises(PermissionFailure):
        raise PermissionFailure("Perm failed")

    with pytest.raises(CertificateValidationFailure):
        raise CertificateValidationFailure("Cert failed")


def test_generic_file_transfer():
    config = {}
    ft = GenericFileTransfer(config, delete=False)

    ft.port = 22
    assert ft.port == 22

    ft.timeout = 30.0
    assert ft.timeout == 30.0

    ft.connect_timeout = 5.0
    assert ft.connect_timeout == 5.0

    ft.atomic = True
    assert ft.atomic is True

    # Test tempname generation
    temp_name = ft.tempname(suffix='.jpg')
    assert temp_name.startswith('tmp')
    assert temp_name.endswith('.jpg')

    # Test dummy connect/close/put
    ft.connect()
    ft.put(local_file="test.jpg")
    ft.close()
