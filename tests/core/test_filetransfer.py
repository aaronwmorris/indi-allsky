from unittest.mock import patch
import pytest

from indi_allsky.filetransfer.generic import GenericFileTransfer
from indi_allsky.filetransfer.exceptions import (
    AuthenticationFailure,
    ConnectionFailure,
    TransferFailure,
    PermissionFailure,
    CertificateValidationFailure,
)




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

    # Test delete mode in put
    ft_del = GenericFileTransfer(config, delete=True)
    with patch.object(ft_del, 'delete', return_value=True) as mock_delete:
        ft_del.put(local_file="test.jpg")
        mock_delete.assert_called_once_with(local_file="test.jpg")

    ft.delete()
