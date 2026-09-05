import queue
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.uploader import FileUploader
from indi_allsky.flask.models import (
    IndiAllSkyDbTaskQueueTable,
    TaskQueueState,
    TaskQueueQueue,
    IndiAllSkyDbCameraTable,
    IndiAllSkyDbImageTable,
)
from indi_allsky.flask import db
from indi_allsky import constants


def test_file_uploader_task_not_found(app):
    with app.app_context():
        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, {}, error_q, upload_q)

        # Nonexistent task ID should log error and return without raising
        uploader.processUpload({'task_id': 999999})


def test_file_uploader_process_upload_task(app, tmp_path):
    with app.app_context():
        # Setup camera and image entry
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Uploader Cam',
                uuid='cam-upload-1',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        test_file = tmp_path / "upload_test.jpg"
        test_file.write_bytes(b"dummy image data")

        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'FILETRANSFER': {
                'CLASSNAME': 'python_ftp',
                'HOST': 'ftp.example.com',
                'USERNAME': 'user',
                'PASSWORD': 'password',
                'PORT': 21,
                'CERT_BYPASS': True,
            },
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_UPLOAD,
                'local_file': str(test_file),
                'remote_file': '/remote/upload_test.jpg',
                'remove_local': False,
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        mock_client = MagicMock()
        with patch('indi_allsky.filetransfer.python_ftp', return_value=mock_client):
            uploader.processUpload({'task_id': task.id})

            mock_client.connect.assert_called_once()
            mock_client.put.assert_called_once()
            mock_client.close.assert_called_once()
            assert task.state == TaskQueueState.SUCCESS


def test_file_uploader_process_upload_failure(app, tmp_path):
    with app.app_context():
        cam = IndiAllSkyDbCameraTable.query.first()
        if not cam:
            cam = IndiAllSkyDbCameraTable(
                name='Uploader Cam',
                uuid='cam-upload-2',
                latitude=-34.9285,
                longitude=138.6007,
                elevation=50,
                nightSunAlt=-6.0,
            )
            db.session.add(cam)
            db.session.commit()

        test_file = tmp_path / "upload_fail_test.jpg"
        test_file.write_bytes(b"dummy image data")

        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'FILETRANSFER': {
                'CLASSNAME': 'python_ftp',
                'HOST': 'ftp.example.com',
                'USERNAME': 'user',
                'PASSWORD': 'password',
                'PORT': 21,
                'CERT_BYPASS': True,
            },
        }

        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_UPLOAD,
                'local_file': str(test_file),
                'remote_file': '/remote/upload_fail_test.jpg',
                'remove_local': False,
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        from indi_allsky.filetransfer.exceptions import ConnectionFailure

        mock_client_cls = MagicMock()
        mock_client_cls.__name__ = 'python_ftp'
        mock_client_inst = MagicMock()
        mock_client_inst.connect.side_effect = ConnectionFailure("Connection timed out")
        mock_client_cls.return_value = mock_client_inst

        with patch('indi_allsky.filetransfer.python_ftp', mock_client_cls):
            uploader.processUpload({'task_id': task.id})

            assert task.state == TaskQueueState.FAILED

