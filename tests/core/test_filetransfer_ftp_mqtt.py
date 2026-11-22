import ftplib
import socket
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from paho.mqtt import MQTTException

from indi_allsky.filetransfer.python_ftp import python_ftp
from indi_allsky.filetransfer.python_ftpes import python_ftpes, FTP_TLS_reuse
from indi_allsky.filetransfer.paho_mqtt import paho_mqtt
from indi_allsky.filetransfer.exceptions import (
    AuthenticationFailure,
    ConnectionFailure,
    TransferFailure,
)


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- python_ftp Tests ---

def test_python_ftp_connect_and_login():
    ftp_client = python_ftp({})

    mock_ftp = MagicMock()
    with patch('ftplib.FTP', return_value=mock_ftp):
        ftp_client.connect(
            hostname='ftp.example.com',
            username='user1',
            password='pass1',
        )
        mock_ftp.connect.assert_called_with(host='ftp.example.com', port=21, timeout=60.0)
        mock_ftp.login.assert_called_with(user='user1', passwd='pass1')
        mock_ftp.set_pasv.assert_called_with(True)

        ftp_client.close()
        mock_ftp.quit.assert_called_once()

    # Close when self.client is None
    ftp_client_none = python_ftp({})
    ftp_client_none.close()


@pytest.mark.parametrize('exc', [
    socket.gaierror("lookup fail"),
    socket.timeout("timed out"),
    ConnectionRefusedError("refused"),
])
def test_python_ftp_connect_failures(exc):
    ftp_client = python_ftp({})
    mock_ftp = MagicMock()
    mock_ftp.connect.side_effect = exc

    with patch('ftplib.FTP', return_value=mock_ftp):
        with pytest.raises(ConnectionFailure):
            ftp_client.connect(
                hostname='ftp.example.com',
                username='user1',
                password='password',
            )


def test_python_ftp_auth_failure():
    ftp_client = python_ftp({})
    mock_ftp = MagicMock()
    mock_ftp.login.side_effect = ftplib.error_perm('530 Login incorrect')

    with patch('ftplib.FTP', return_value=mock_ftp):
        with pytest.raises(AuthenticationFailure):
            ftp_client.connect(
                hostname='ftp.example.com',
                username='user1',
                password='badpassword',
            )


def test_python_ftp_put(tmp_path):
    local_file = tmp_path / "test.jpg"
    local_file.write_bytes(b"image data")

    ftp_client = python_ftp({})
    mock_ftp = MagicMock()
    ftp_client.client = mock_ftp

    # Normal upload with nested remote path
    ftp_client.put(
        local_file=str(local_file),
        remote_file='subdir/nested/remote.jpg',
    )
    mock_ftp.mkd.assert_any_call('subdir')
    mock_ftp.mkd.assert_any_call('subdir/nested')
    mock_ftp.storbinary.assert_called_once()
    mock_ftp.sendcmd.assert_any_call('SITE CHMOD 644 subdir/nested/remote.jpg')
    mock_ftp.sendcmd.assert_any_call('SITE CHMOD 755 subdir/nested')

    # mkd error (dir already exists) is caught
    mock_ftp.reset_mock()
    mock_ftp.mkd.side_effect = ftplib.error_perm("Directory already exists")
    ftp_client.put(
        local_file=str(local_file),
        remote_file='existing/dir/remote.jpg',
    )
    mock_ftp.storbinary.assert_called_once()

    # chmod error is caught
    mock_ftp.reset_mock()
    mock_ftp.sendcmd.side_effect = ftplib.error_perm("Chmod failed")
    ftp_client.put(
        local_file=str(local_file),
        remote_file='existing/dir/remote.jpg',
    )

    # storbinary error raises TransferFailure
    mock_ftp.reset_mock()
    mock_ftp.storbinary.side_effect = ftplib.error_perm("Disk full")
    with pytest.raises(TransferFailure):
        ftp_client.put(
            local_file=str(local_file),
            remote_file='existing/dir/remote.jpg',
        )


# --- python_ftpes Tests ---

def test_python_ftpes_connect_and_login():
    ftpes_client = python_ftpes({})

    mock_ftpes = MagicMock()
    with patch('indi_allsky.filetransfer.python_ftpes.FTP_TLS_reuse', return_value=mock_ftpes):
        ftpes_client.connect(
            hostname='ftpes.example.com',
            username='user1',
            password='pass1',
        )
        mock_ftpes.connect.assert_called_with(host='ftpes.example.com', port=21, timeout=60.0)
        mock_ftpes.auth.assert_called_once()
        mock_ftpes.prot_p.assert_called_once()
        mock_ftpes.login.assert_called_with(user='user1', passwd='pass1')
        mock_ftpes.set_pasv.assert_called_with(True)

        ftpes_client.close()
        mock_ftpes.quit.assert_called_once()

    # Close when self.client is None
    ftpes_client_none = python_ftpes({})
    ftpes_client_none.close()


@pytest.mark.parametrize('exc', [
    socket.gaierror("lookup fail"),
    socket.timeout("timed out"),
    ConnectionRefusedError("refused"),
])
def test_python_ftpes_connect_failures(exc):
    ftpes_client = python_ftpes({})
    mock_ftpes = MagicMock()
    mock_ftpes.connect.side_effect = exc

    with patch('indi_allsky.filetransfer.python_ftpes.FTP_TLS_reuse', return_value=mock_ftpes):
        with pytest.raises(ConnectionFailure):
            ftpes_client.connect(
                hostname='ftpes.example.com',
                username='user1',
                password='password',
            )


def test_python_ftpes_auth_failure():
    ftpes_client = python_ftpes({})
    mock_ftpes = MagicMock()
    mock_ftpes.login.side_effect = ftplib.error_perm('530 Login incorrect')

    with patch('indi_allsky.filetransfer.python_ftpes.FTP_TLS_reuse', return_value=mock_ftpes):
        with pytest.raises(AuthenticationFailure):
            ftpes_client.connect(
                hostname='ftpes.example.com',
                username='user1',
                password='badpassword',
            )


def test_python_ftpes_put(tmp_path):
    local_file = tmp_path / "test.jpg"
    local_file.write_bytes(b"image data")

    ftpes_client = python_ftpes({})
    mock_ftpes = MagicMock()
    ftpes_client.client = mock_ftpes

    # Normal upload with nested remote path
    ftpes_client.put(
        local_file=str(local_file),
        remote_file='subdir/nested/remote.jpg',
    )
    mock_ftpes.mkd.assert_any_call('subdir')
    mock_ftpes.mkd.assert_any_call('subdir/nested')
    mock_ftpes.storbinary.assert_called_once()
    mock_ftpes.sendcmd.assert_any_call('SITE CHMOD 644 subdir/nested/remote.jpg')
    mock_ftpes.sendcmd.assert_any_call('SITE CHMOD 755 subdir/nested')

    # mkd error is caught
    mock_ftpes.reset_mock()
    mock_ftpes.mkd.side_effect = ftplib.error_perm("Directory already exists")
    ftpes_client.put(
        local_file=str(local_file),
        remote_file='existing/dir/remote.jpg',
    )
    mock_ftpes.storbinary.assert_called_once()

    # chmod error is caught
    mock_ftpes.reset_mock()
    mock_ftpes.sendcmd.side_effect = ftplib.error_perm("Chmod failed")
    ftpes_client.put(
        local_file=str(local_file),
        remote_file='existing/dir/remote.jpg',
    )

    # storbinary error raises TransferFailure
    mock_ftpes.reset_mock()
    mock_ftpes.storbinary.side_effect = ftplib.error_perm("Disk full")
    with pytest.raises(TransferFailure):
        ftpes_client.put(
            local_file=str(local_file),
            remote_file='existing/dir/remote.jpg',
        )


def test_ftpes_tls_reuse():
    tls_reuse = FTP_TLS_reuse()
    tls_reuse.host = 'ftpes.example.com'
    mock_sock = MagicMock()
    mock_sock.session = MagicMock()
    tls_reuse.sock = mock_sock
    tls_reuse.context = MagicMock()

    mock_conn = MagicMock()
    with patch('ftplib.FTP.ntransfercmd', return_value=(mock_conn, 1024)):
        # When _prot_p is True
        tls_reuse._prot_p = True
        conn, size = tls_reuse.ntransfercmd('STOR test.jpg')
        assert size == 1024
        tls_reuse.context.wrap_socket.assert_called_once_with(
            mock_conn,
            server_hostname='ftpes.example.com',
            session=mock_sock.session,
        )

        # When _prot_p is False
        tls_reuse._prot_p = False
        conn2, size2 = tls_reuse.ntransfercmd('STOR test.jpg')
        assert conn2 == mock_conn


# --- paho_mqtt Tests ---

def test_paho_mqtt_connect_and_options():
    mqtt_client = paho_mqtt({})

    # TLS with cert_bypass=False
    mqtt_client.connect(
        transport='tcp',
        protocol='3.1.1',
        hostname='mqtt.example.com',
        username='mq_user',
        password='mq_pass',
        tls=True,
        cert_bypass=False,
    )
    assert mqtt_client.mq_hostname == 'mqtt.example.com'
    assert mqtt_client.mq_auth == {'username': 'mq_user', 'password': 'mq_pass'}
    assert mqtt_client.mq_tls['insecure'] is False
    assert mqtt_client.mq_tls['cert_reqs'] == ssl.CERT_REQUIRED

    # TLS with cert_bypass=True
    mqtt_client.connect(
        transport='tcp',
        protocol='3.1.1',
        hostname='mqtt.example.com',
        username='mq_user',
        password='mq_pass',
        tls=True,
        cert_bypass=True,
    )
    assert mqtt_client.mq_tls['insecure'] is True
    assert mqtt_client.mq_tls['cert_reqs'] == ssl.CERT_NONE

    # No password, no username, no TLS
    mqtt_client_none = paho_mqtt({})
    mqtt_client_none.connect(
        transport='tcp',
        protocol='3.1.1',
        hostname='mqtt.example.com',
        username='',
        password='',
        tls=False,
        cert_bypass=False,
    )
    assert mqtt_client_none.mq_auth is None
    assert mqtt_client_none.mq_tls is None

    mqtt_client.close()


def test_paho_mqtt_put(tmp_path):
    local_file = tmp_path / "image.jpg"
    local_file.write_bytes(b"jpeg bytes")

    mqtt_client = paho_mqtt({})
    mqtt_client.connect(
        transport='tcp',
        protocol='MQTTv311',
        hostname='mqtt.example.com',
        username='user',
        password='pass',
        tls=False,
        cert_bypass=False,
    )

    with patch('paho.mqtt.publish.multiple') as mock_pub:
        # publish_image=True
        mqtt_client.put(
            local_file=str(local_file),
            base_topic='allsky',
            qos=1,
            mq_data={'temp': 22.5},
            image_topic='latest',
            publish_image=True,
        )
        mock_pub.assert_called_once()
        messages = mock_pub.call_args[0][0]
        assert len(messages) == 2
        assert messages[0]['topic'] == 'allsky/latest'
        assert messages[0]['payload'] == b'jpeg bytes'
        assert messages[1]['topic'] == 'allsky/temp'
        assert messages[1]['payload'] == 22.5

        # publish_image=False with data
        mock_pub.reset_mock()
        mqtt_client.put(
            local_file=str(local_file),
            base_topic='allsky',
            qos=1,
            mq_data={'temp': 23.0},
            image_topic='latest',
            publish_image=False,
        )
        mock_pub.assert_called_once()
        messages2 = mock_pub.call_args[0][0]
        assert len(messages2) == 1
        assert messages2[0]['topic'] == 'allsky/temp'

        # empty message list (publish_image=False, mq_data={}) -> returns early
        mock_pub.reset_mock()
        mqtt_client.put(
            local_file=str(local_file),
            base_topic='allsky',
            qos=1,
            mq_data={},
            image_topic='latest',
            publish_image=False,
        )
        mock_pub.assert_not_called()


@pytest.mark.parametrize('raised_exc, expected_exc', [
    (socket.gaierror("lookup fail"), ConnectionFailure),
    (socket.timeout("timed out"), ConnectionFailure),
    (ssl.SSLCertVerificationError("cert fail"), ConnectionFailure),
    (ConnectionRefusedError("refused"), ConnectionFailure),
    (OSError("os err"), ConnectionFailure),
    (MQTTException("mqtt err"), AuthenticationFailure),
    (ValueError("bad value"), TransferFailure),
])
def test_paho_mqtt_put_exceptions(tmp_path, raised_exc, expected_exc):
    local_file = tmp_path / "image.jpg"
    local_file.write_bytes(b"jpeg bytes")

    mqtt_client = paho_mqtt({})
    mqtt_client.connect(
        transport='tcp',
        protocol='MQTTv311',
        hostname='mqtt.example.com',
        username='user',
        password='pass',
        tls=False,
        cert_bypass=False,
    )

    with patch('paho.mqtt.publish.multiple', side_effect=raised_exc):
        with pytest.raises(expected_exc):
            mqtt_client.put(
                local_file=str(local_file),
                base_topic='allsky',
                qos=1,
                mq_data={'temp': 22.5},
                image_topic='latest',
                publish_image=True,
            )
