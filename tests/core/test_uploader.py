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
from sqlalchemy.orm.exc import NoResultFound
from indi_allsky.filetransfer.exceptions import (
    ConnectionFailure,
    AuthenticationFailure,
    CertificateValidationFailure,
    TransferFailure,
    PermissionFailure,
)



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


def _get_or_create_cam():
    cam = IndiAllSkyDbCameraTable.query.first()
    if not cam:
        cam = IndiAllSkyDbCameraTable(
            name='Uploader Cam Shared',
            uuid='cam-upload-shared-1',
            latitude=-34.9285,
            longitude=138.6007,
            elevation=50,
            nightSunAlt=-6.0,
        )
        db.session.add(cam)
        db.session.commit()
    return cam


def _create_image(tmp_path, filename="upload_img.jpg", data=None):
    from datetime import datetime
    cam = _get_or_create_cam()
    img_file = tmp_path / filename
    img_file.write_bytes(b"image bytes")
    img = IndiAllSkyDbImageTable(
        filename=str(img_file),
        dayDate=datetime.now().date(),
        createDate=datetime.now(),
        exposure=1.0,
        gain=100.0,
        adu=100.0,
        camera_id=cam.id,
        data=data,
    )
    db.session.add(img)
    db.session.commit()
    return img, img_file


def test_uploader_lifecycle_and_run(tmp_path):
    error_q = queue.Queue()
    upload_q = queue.Queue()
    uploader = FileUploader(0, {}, error_q, upload_q)

    assert not uploader.stopped()
    uploader.stop()
    assert uploader.stopped()

    # saferun exits when stopped
    uploader.saferun()

    # default image_dir when IMAGE_FOLDER not in config
    assert "html" in str(uploader.image_dir)

    # run() catches uncaught exceptions and puts into error_q
    uploader2 = FileUploader(1, {}, error_q, upload_q)
    with patch.object(uploader2, "saferun", side_effect=RuntimeError("Worker error")):
        with pytest.raises(RuntimeError):
            uploader2.run()
        err, tb = error_q.get_nowait()
        assert "Worker error" in err

    # saferun empty timeout and item retrieval
    uploader3 = FileUploader(2, {}, error_q, upload_q)
    call_count = [0]
    orig_get = upload_q.get
    def side_effect(timeout=11):
        if call_count[0] == 0:
            call_count[0] += 1
            raise queue.Empty()
        uploader3.stop()
        return orig_get(block=False)

    upload_q.put({'task_id': 999})
    def mock_process(u_dict):
        pass
    uploader3.processUpload = mock_process
    with patch.object(upload_q, "get", side_effect=side_effect):
        uploader3.saferun()



def test_uploader_cleanup(tmp_path):
    error_q = queue.Queue()
    upload_q = queue.Queue()
    uploader = FileUploader(0, {}, error_q, upload_q)

    test_file = tmp_path / "cleanup_test.jpg"
    test_file.write_bytes(b"data")

    # remove_local False does not delete
    uploader.cleanup(test_file, remove_local=False)
    assert test_file.exists()

    # remove_local True unlinks
    uploader.cleanup(test_file, remove_local=True)
    assert not test_file.exists()

    # FileNotFoundError handled gracefully
    uploader.cleanup(test_file, remove_local=True)

    # PermissionError handled gracefully
    test_file2 = tmp_path / "cleanup_test2.jpg"
    test_file2.write_bytes(b"data")
    with patch.object(Path, "unlink", side_effect=PermissionError("Permission denied")):
        uploader.cleanup(test_file2, remove_local=True)


def test_uploader_entry_resolution_and_validation(app, tmp_path):
    with app.app_context():
        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, {'FILETRANSFER': {'HOST': 'localhost', 'USERNAME': 'u', 'PASSWORD': 'p', 'CLASSNAME': 'python_ftp', 'PORT': 21}}, error_q, upload_q)

        # 1. Invalid entry_model
        t1 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={'action': constants.TRANSFER_UPLOAD, 'model': 'InvalidModelName', 'id': 1},
        )
        db.session.add(t1)
        db.session.commit()
        uploader.processUpload({'task_id': t1.id})
        assert t1.state == TaskQueueState.FAILED
        assert 'Model not found' in t1.result

        # 2. Entry ID not found
        t2 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={'action': constants.TRANSFER_UPLOAD, 'model': 'IndiAllSkyDbImageTable', 'id': 999999},
        )
        db.session.add(t2)
        db.session.commit()
        uploader.processUpload({'task_id': t2.id})
        assert t2.state == TaskQueueState.FAILED
        assert 'not found in IndiAllSkyDbImageTable' in t2.result

        # 3. No model, no local_file, no s3_key
        t3 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={'action': constants.TRANSFER_UPLOAD},
        )
        db.session.add(t3)
        db.session.commit()
        uploader.processUpload({'task_id': t3.id})
        assert t3.state == TaskQueueState.FAILED
        assert 'Entry model or filename not defined' in t3.result

        # 4. Hostname missing for TRANSFER_UPLOAD
        test_file = tmp_path / "nohost.jpg"
        test_file.write_bytes(b"x")
        t4 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={'action': constants.TRANSFER_UPLOAD, 'local_file': str(test_file), 'remote_file': '/r.jpg'},
        )
        db.session.add(t4)
        db.session.commit()
        uploader_nohost = FileUploader(0, {'FILETRANSFER': {'HOST': '', 'USERNAME': 'u', 'PASSWORD': 'p'}}, error_q, upload_q)
        uploader_nohost.processUpload({'task_id': t4.id})
        assert t4.state == TaskQueueState.FAILED
        assert 'Hostname not set' in t4.result

        # 5. Unknown filetransfer class
        t4.state = TaskQueueState.QUEUED
        db.session.commit()
        uploader_badcls = FileUploader(0, {'FILETRANSFER': {'HOST': 'host', 'USERNAME': 'u', 'PASSWORD': 'p', 'CLASSNAME': 'unknown_class', 'PORT': 21}}, error_q, upload_q)
        uploader_badcls.processUpload({'task_id': t4.id})
        assert t4.state == TaskQueueState.FAILED
        assert 'Unknown filetransfer class' in t4.result



        # 6. Invalid transfer action
        t5 = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={'action': 'INVALID_ACTION', 'local_file': str(test_file)},
        )
        db.session.add(t5)
        db.session.commit()
        with pytest.raises(Exception, match='Invalid transfer action'):
            uploader.processUpload({'task_id': t5.id})
        assert t5.state == TaskQueueState.FAILED


def test_uploader_transfer_upload_success_with_entry(app, tmp_path):
    with app.app_context():
        img, img_file = _create_image(tmp_path, "upload_entry.jpg")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'FILETRANSFER': {
                'CLASSNAME': 'python_ftp',
                'HOST': 'ftp.example.com',
                'USERNAME': 'user',
                'PASSWORD': 'password',
                'PORT': 21,
                'CERT_BYPASS': True,
                'CONNECT_TIMEOUT': 5,
                'TIMEOUT': 10,
                'ATOMIC_TRANSFERS': True,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_UPLOAD,
                'model': 'IndiAllSkyDbImageTable',
                'id': img.id,
                'remote_file': '/remote/upload_entry.jpg',
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
            assert task.state == TaskQueueState.SUCCESS
            assert img.uploaded is True


def test_uploader_transfer_s3(app, tmp_path):
    with app.app_context():
        img, img_file = _create_image(tmp_path, "s3_entry.jpg")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'S3UPLOAD': {
                'CLASSNAME': 'boto3_s3',
                'ACCESS_KEY': 'ak',
                'SECRET_KEY': 'sk',
                'REGION': 'us-east-1',
                'HOST': 's3.amazonaws.com',
                'BUCKET': 'mybucket',
                'URL_TEMPLATE': 'https://{bucket}/{key}',
                'TLS': True,
                'CERT_BYPASS': False,
                'STORAGE_CLASS': 'STANDARD',
                'ACL': 'public-read',
                'PORT': 443,
            },
            'SYNCAPI': {'ENABLE': False},
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_S3,
                'model': 'IndiAllSkyDbImageTable',
                'id': img.id,
                'metadata': {'type': constants.IMAGE},
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        # 1. Unknown S3 class
        config_bad = dict(config)
        config_bad['S3UPLOAD'] = dict(config['S3UPLOAD'])
        config_bad['S3UPLOAD']['CLASSNAME'] = 'nonexistent_s3'
        uploader_bad = FileUploader(0, config_bad, error_q, upload_q)
        uploader_bad.processUpload({'task_id': task.id})
        assert task.state == TaskQueueState.FAILED

        # 2. Successful S3 transfer
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        mock_client = MagicMock()
        with patch('indi_allsky.filetransfer.boto3_s3', return_value=mock_client):
            with patch.object(uploader, '_syncapi') as mock_syncapi:
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.SUCCESS
                assert img.s3_key is not None
                mock_syncapi.assert_called_once()


def test_uploader_delete_s3(app, tmp_path):
    with app.app_context():
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'S3UPLOAD': {
                'CLASSNAME': 'boto3_s3',
                'ACCESS_KEY': 'ak',
                'SECRET_KEY': 'sk',
                'REGION': 'us-east-1',
                'HOST': 's3.amazonaws.com',
                'BUCKET': 'mybucket',
                'TLS': True,
                'CERT_BYPASS': False,
                'PORT': 443,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.DELETE_S3,
                's3_key': 'test_key.jpg',
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        # 1. Unknown S3 class
        config_bad = dict(config)
        config_bad['S3UPLOAD'] = dict(config['S3UPLOAD'])
        config_bad['S3UPLOAD']['CLASSNAME'] = 'nonexistent_s3'
        uploader_bad = FileUploader(0, config_bad, error_q, upload_q)
        uploader_bad.processUpload({'task_id': task.id})
        assert task.state == TaskQueueState.FAILED

        # 2. Successful DELETE_S3
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        mock_client = MagicMock()
        with patch('indi_allsky.filetransfer.boto3_s3', return_value=mock_client):
            uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.SUCCESS
            mock_client.put.assert_called_once()


def test_uploader_transfer_mqtt(app, tmp_path):
    with app.app_context():
        test_file = tmp_path / "mqtt.jpg"
        test_file.write_bytes(b"mqtt")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'MQTTPUBLISH': {
                'TRANSPORT': 'tcp',
                'HOST': 'localhost',
                'USERNAME': 'u',
                'PASSWORD': 'p',
                'TLS': False,
                'BASE_TOPIC': 'allsky',
                'QOS': 0,
                'PORT': 1883,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_MQTT,
                'local_file': str(test_file),
                'image_topic': 'camera/image',
                'metadata': {'info': 'data'},
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()

        # 1. Hostname not set
        cfg_nohost = dict(config)
        cfg_nohost['MQTTPUBLISH'] = dict(config['MQTTPUBLISH'])
        cfg_nohost['MQTTPUBLISH']['HOST'] = ''
        uploader_nohost = FileUploader(0, cfg_nohost, error_q, upload_q)
        uploader_nohost.processUpload({'task_id': task.id})
        assert task.state == TaskQueueState.FAILED

        # 2. Unknown class
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        uploader = FileUploader(0, config, error_q, upload_q)
        mock_ft = MagicMock()
        del mock_ft.paho_mqtt
        with patch('indi_allsky.uploader.filetransfer', mock_ft):
            uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.FAILED

        # 3. Successful MQTT
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        mock_client = MagicMock()
        with patch('indi_allsky.filetransfer.paho_mqtt', return_value=mock_client):
            uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.SUCCESS


def test_uploader_transfer_sync_v1(app, tmp_path):
    with app.app_context():
        img, img_file = _create_image(tmp_path, "sync_v1.jpg")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'SYNCAPI': {
                'BASEURL': 'https://api.example.com',
                'USERNAME': 'user',
                'APIKEY': 'key',
                'CERT_BYPASS': True,
                'CONNECT_TIMEOUT': 5.0,
                'TIMEOUT': 10.0,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_SYNC_V1,
                'model': 'IndiAllSkyDbImageTable',
                'id': img.id,
                'metadata': {'type': constants.IMAGE},
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        # 1. Unknown class
        mock_ft = MagicMock()
        del mock_ft.requests_syncapi_v1
        with patch('indi_allsky.uploader.filetransfer', mock_ft):
            uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.FAILED

        # 2. Success
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        mock_client = MagicMock()
        mock_client.put.return_value = {'id': 777}
        with patch('indi_allsky.filetransfer.requests_syncapi_v1', return_value=mock_client):
            uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.SUCCESS
            assert img.sync_id == 777


def test_uploader_transfer_youtube(app, tmp_path):
    with app.app_context():
        img, img_file = _create_image(tmp_path, "yt_video.mp4")
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_YOUTUBE,
                'model': 'IndiAllSkyDbImageTable',
                'id': img.id,
                'metadata': {'title': 'Allsky Video'},
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, {}, error_q, upload_q)

        # 1. No credentials in miscDb
        with patch.object(uploader._miscDb, 'getState', side_effect=NoResultFound()):
            with pytest.raises(Exception, match='Youtube authorization credentials not found'):
                uploader.processUpload({'task_id': task.id})
            assert task.state == TaskQueueState.FAILED

        # 2. Unknown class
        task.state = TaskQueueState.QUEUED
        db.session.commit()
        mock_ft = MagicMock()
        del mock_ft.youtube_oauth2
        with patch.object(uploader._miscDb, 'getState', return_value='{"token": "xyz"}'):
            with patch('indi_allsky.uploader.filetransfer', mock_ft):
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.FAILED


        # 3. Success with img.data is None
        task.state = TaskQueueState.QUEUED
        img.data = None
        db.session.commit()
        mock_client = MagicMock()
        mock_client.put.return_value = {'id': 'yt-vid-123'}
        with patch.object(uploader._miscDb, 'getState', return_value='{"token": "xyz"}'):
            with patch('indi_allsky.filetransfer.youtube_oauth2', return_value=mock_client):
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.SUCCESS
                assert img.data['youtube_id'] == 'yt-vid-123'

        # 4. Success with img.data already having entries
        task.state = TaskQueueState.QUEUED
        img.data = {'existing': True}
        db.session.commit()
        with patch.object(uploader._miscDb, 'getState', return_value='{"token": "xyz"}'):
            with patch('indi_allsky.filetransfer.youtube_oauth2', return_value=mock_client):
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.SUCCESS
                assert img.data['youtube_id'] == 'yt-vid-123'
                assert img.data['existing'] is True


@pytest.mark.parametrize("exc_cls, notification_subcat", [
    (ConnectionFailure, 'connection'),
    (AuthenticationFailure, 'authentication'),
    (CertificateValidationFailure, 'certificate'),
])
def test_uploader_connect_exceptions(app, tmp_path, exc_cls, notification_subcat):
    with app.app_context():
        test_file = tmp_path / "conn_fail.jpg"
        test_file.write_bytes(b"data")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'FILETRANSFER': {
                'CLASSNAME': 'python_ftp',
                'HOST': 'ftp.example.com',
                'USERNAME': 'user',
                'PASSWORD': 'password',
                'PORT': 21,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_UPLOAD,
                'local_file': str(test_file),
                'remote_file': '/r.jpg',
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        mock_client_cls = MagicMock()
        mock_client_cls.__name__ = 'python_ftp'
        mock_client = MagicMock()
        mock_client.connect.side_effect = exc_cls("Mock connect fail")
        mock_client_cls.return_value = mock_client
        with patch('indi_allsky.filetransfer.python_ftp', mock_client_cls):
            with patch.object(uploader._miscDb, 'addNotification') as mock_notif:
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.FAILED
                mock_client.close.assert_called()
                mock_notif.assert_called_once()
                assert mock_notif.call_args[0][1] == notification_subcat


@pytest.mark.parametrize("exc_cls, notification_subcat", [
    (ConnectionFailure, 'connection'),
    (AuthenticationFailure, 'authentication'),
    (CertificateValidationFailure, 'certificate'),
    (TransferFailure, 'filetransfer'),
    (PermissionFailure, 'permission'),
])
def test_uploader_put_exceptions(app, tmp_path, exc_cls, notification_subcat):
    with app.app_context():
        test_file = tmp_path / "put_fail.jpg"
        test_file.write_bytes(b"data")
        config = {
            'IMAGE_FOLDER': str(tmp_path),
            'FILETRANSFER': {
                'CLASSNAME': 'python_ftp',
                'HOST': 'ftp.example.com',
                'USERNAME': 'user',
                'PASSWORD': 'password',
                'PORT': 21,
            },
        }
        task = IndiAllSkyDbTaskQueueTable(
            queue=TaskQueueQueue.UPLOAD,
            state=TaskQueueState.QUEUED,
            data={
                'action': constants.TRANSFER_UPLOAD,
                'local_file': str(test_file),
                'remote_file': '/r.jpg',
            },
        )
        db.session.add(task)
        db.session.commit()

        error_q = queue.Queue()
        upload_q = queue.Queue()
        uploader = FileUploader(0, config, error_q, upload_q)

        mock_client_cls = MagicMock()
        mock_client_cls.__name__ = 'python_ftp'
        mock_client = MagicMock()
        mock_client.put.side_effect = exc_cls("Mock put fail")
        mock_client_cls.return_value = mock_client
        with patch('indi_allsky.filetransfer.python_ftp', mock_client_cls):
            with patch.object(uploader._miscDb, 'addNotification') as mock_notif:
                uploader.processUpload({'task_id': task.id})
                assert task.state == TaskQueueState.FAILED
                mock_client.close.assert_called()
                mock_notif.assert_called_once()
                assert mock_notif.call_args[0][1] == notification_subcat



def test_uploader_syncapi_branches(app, tmp_path):
    with app.app_context():
        error_q = queue.Queue()
        upload_q = queue.Queue()

        # 1. Disabled
        uploader1 = FileUploader(0, {'SYNCAPI': {'ENABLE': False}}, error_q, upload_q)
        uploader1._syncapi(None, {})
        assert upload_q.empty()

        # 2. POST_S3 False
        uploader2 = FileUploader(0, {'SYNCAPI': {'ENABLE': True, 'POST_S3': False}}, error_q, upload_q)
        uploader2._syncapi(None, {})
        assert upload_q.empty()

        # 3. Not asset_entry
        uploader3 = FileUploader(0, {'SYNCAPI': {'ENABLE': True, 'POST_S3': True}}, error_q, upload_q)
        uploader3._syncapi(None, {})
        assert upload_q.empty()

        # 4. Image syncing disabled
        img, _ = _create_image(tmp_path, "sync_test.jpg")
        cfg4 = {'SYNCAPI': {'ENABLE': True, 'POST_S3': True, 'UPLOAD_IMAGE': 0}}
        uploader4 = FileUploader(0, cfg4, error_q, upload_q)
        uploader4._syncapi(img, {'type': constants.IMAGE})
        assert upload_q.empty()

        # 5. Image remain != 0
        cfg5 = {'SYNCAPI': {'ENABLE': True, 'POST_S3': True, 'UPLOAD_IMAGE': 5}, 'EXPOSURE_PERIOD': 30}
        img.id = 7
        uploader5 = FileUploader(0, cfg5, error_q, upload_q)
        uploader5._syncapi(img, {'type': constants.IMAGE})
        assert upload_q.empty()

        # 6. Image remain == 0
        img.id = 10
        uploader5._syncapi(img, {'type': constants.IMAGE})
        assert not upload_q.empty()
        t_id = upload_q.get_nowait()
        assert 'task_id' in t_id

        # 7. Non-image metadata
        uploader5._syncapi(img, {'type': constants.VIDEO})
        assert not upload_q.empty()
        upload_q.get_nowait()


