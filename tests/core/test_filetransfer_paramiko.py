import socket
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from indi_allsky.filetransfer.paramiko_sftp import paramiko_sftp
from indi_allsky.filetransfer.exceptions import (
    AuthenticationFailure,
    ConnectionFailure,
    TransferFailure,
)


def test_paramiko_sftp_connect_password(tmp_path):
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        transfer = paramiko_sftp({'FILETRANSFER': {}})
        assert transfer._port == 22

        transfer.connect(
            hostname='sftp.example.com',
            username='user1',
            password='secretpassword',
            cert_bypass=True,
        )

        mock_ssh.set_missing_host_key_policy.assert_called()
        mock_ssh.connect.assert_called_with(
            'sftp.example.com',
            port=22,
            username='user1',
            timeout=transfer.timeout,
            password='secretpassword',
        )
        assert transfer.sftp is mock_sftp

        # Close
        transfer.close()
        mock_sftp.close.assert_called_once()
        mock_ssh.close.assert_called_once()


def test_paramiko_sftp_connect_private_key(tmp_path):
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        transfer = paramiko_sftp({'FILETRANSFER': {}})
        transfer.connect(
            hostname='sftp.example.com',
            username='user1',
            password='keypassphrase',
            private_key='/path/to/id_rsa',
        )

        mock_ssh.connect.assert_called_with(
            'sftp.example.com',
            port=22,
            username='user1',
            timeout=transfer.timeout,
            key_filename='/path/to/id_rsa',
            passphrase='keypassphrase',
        )


@pytest.mark.parametrize('raised_exc, expected_exc', [
    (Exception('auth failed'), AuthenticationFailure),
    (Exception('no valid conn'), ConnectionFailure),
    (socket.gaierror('dns error'), ConnectionFailure),
    (socket.timeout('timed out'), ConnectionFailure),
])
def test_paramiko_sftp_connect_exceptions(raised_exc, expected_exc):
    import paramiko
    mock_ssh = MagicMock()
    if expected_exc == AuthenticationFailure:
        mock_ssh.connect.side_effect = paramiko.ssh_exception.AuthenticationException('auth failed')
    elif str(raised_exc) == 'no valid conn':
        mock_ssh.connect.side_effect = paramiko.ssh_exception.NoValidConnectionsError({'127.0.0.1': 22})
    else:
        mock_ssh.connect.side_effect = raised_exc

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        transfer = paramiko_sftp({'FILETRANSFER': {}})
        with pytest.raises(expected_exc):
            transfer.connect(
                hostname='sftp.example.com',
                username='user1',
                password='secretpassword',
            )


def test_paramiko_sftp_put_success(tmp_path):
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        transfer = paramiko_sftp({'FILETRANSFER': {}})
        transfer.connect(hostname='sftp.example.com', username='user1', password='pass')

        local_file = tmp_path / "image.jpg"
        local_file.write_bytes(b"image data bytes")

        # First dir creation raises OSError (exists), chmod on dir raises OSError
        def fake_mkdir(d):
            if d == 'dest':
                raise OSError('Directory already exists')
        mock_sftp.mkdir.side_effect = fake_mkdir

        def fake_chmod(target, mode):
            if target == 'dest':
                raise OSError('Permission error on dir chmod')
        mock_sftp.chmod.side_effect = fake_chmod

        transfer.put(local_file=str(local_file), remote_file='dest/sub/image.jpg')

        mock_sftp.put.assert_called_with(str(local_file), 'dest/sub/image.jpg')
        assert mock_sftp.chmod.call_count == 2


def test_paramiko_sftp_put_exceptions(tmp_path):
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        transfer = paramiko_sftp({'FILETRANSFER': {}})
        transfer.connect(hostname='sftp.example.com', username='user1', password='pass')

        local_file = tmp_path / "image.jpg"
        local_file.write_bytes(b"data")

        # PermissionError
        mock_sftp.put.side_effect = PermissionError('Access denied')
        with pytest.raises(TransferFailure):
            transfer.put(local_file=str(local_file), remote_file='dest/image.jpg')

        # FileNotFoundError (~ in remote paths)
        mock_sftp.put.side_effect = FileNotFoundError('No such file or directory')
        with pytest.raises(TransferFailure):
            transfer.put(local_file=str(local_file), remote_file='~/dest/image.jpg')

        # OSError on file chmod
        mock_sftp.put.side_effect = None
        mock_sftp.chmod.side_effect = OSError('Cannot chmod')
        transfer.put(local_file=str(local_file), remote_file='dest/image.jpg')
