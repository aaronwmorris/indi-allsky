import ftplib
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.filetransfer.python_ftp import python_ftp
from indi_allsky.filetransfer.python_ftpes import python_ftpes
from indi_allsky.filetransfer.paho_mqtt import paho_mqtt
from indi_allsky.filetransfer.exceptions import AuthenticationFailure, ConnectionFailure


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


def test_paho_mqtt_connect_and_transfer():
    mqtt_client = paho_mqtt({})

    mqtt_client.connect(
        transport='tcp',
        protocol='3.1.1',
        hostname='mqtt.example.com',
        username='mq_user',
        password='mq_pass',
        tls=True,
        cert_bypass=True,
    )

    assert mqtt_client.mq_hostname == 'mqtt.example.com'
    assert mqtt_client.mq_auth['username'] == 'mq_user'
    assert mqtt_client.mq_tls['insecure'] is True

    mqtt_client.close()
