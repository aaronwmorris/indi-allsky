import sys
import json
from pathlib import Path
from multiprocessing import Array, Queue
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.camera.libcamera_mqtt import (
    IndiClientLibCameraMqttGeneric,
    IndiClientLibCameraImx477Mqtt,
    IndiClientLibCameraImx378Mqtt,
    IndiClientLibCameraImx708Mqtt,
    IndiClientLibCameraOv64a40OwlSightMqtt,
)
from indi_allsky import constants


@pytest.fixture
def mock_mqtt_client():
    client = MagicMock()
    return client


def test_libcamera_mqtt_init_and_connect_options(flask_app):
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client), \
         patch('shutil.which', return_value='/usr/bin/rpicam-still'):

        # 1. Unknown protocol
        bad_config = {'LIBCAMERA': {'MQTT_PROTOCOL': 'NONEXISTENT'}}
        with pytest.raises(AttributeError):
            IndiClientLibCameraMqttGeneric(
                bad_config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
            )

        # 2. TLS with cert_bypass=False
        cfg1 = {
            'LIBCAMERA': {
                'MQTT_USERNAME': 'admin',
                'MQTT_PASSWORD': 'pw',
                'MQTT_TLS': True,
                'MQTT_CERT_BYPASS': False,
            }
        }
        cam1 = IndiClientLibCameraMqttGeneric(
            cfg1, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        assert cam1.qos == 0
        mock_client.username_pw_set.assert_called_with(username='admin', password='pw')
        assert mock_client.tls_set.called

        # 3. Disconnect
        cam1.disconnectServer()
        mock_client.disconnect.assert_called_once()
        mock_client.loop_stop.assert_called_once()


def test_libcamera_mqtt_exposure_and_commands(flask_app, tmp_path):
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])  # night=1

    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client), \
         patch('shutil.which', return_value='/usr/bin/rpicam-still'):

        config = {
            'LIBCAMERA': {
                'CAMERA_ID': 1,
                'IMAGE_FILE_TYPE': 'dng',
                'IMAGE_FILE_TYPE_DAY': 'png',
                'IMMEDIATE': True,
                'IMMEDIATE_DAY': True,
                'AWB_ENABLE': True,
                'AWB': 'indoor',
                'CCM_DISABLE': True,
                'EXTRA_OPTIONS': '--lens-position 0.0',
            }
        }

        cam = IndiClientLibCameraMqttGeneric(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        cam.findCcd()

        # Night exposure (DNG format, AWB enabled, CCM disabled, extra options)
        cam.setCcdExposure(exposure=2.0, gain=5.0, binning=1, sync=False)
        assert cam.active_exposure is True
        assert mock_client.publish.called

        # Second exposure ignored when active
        cam.setCcdExposure(exposure=1.0, gain=5.0, binning=1)

        # Status while waiting on image only
        cam.user_data['waiting_on_metadata'] = False
        cam.user_data['waiting_on_image'] = True
        ready, status = cam.getCcdExposureStatus()
        assert ready is False
        assert status == 'BUSY'

        # Daytime exposure (PNG format, AWB enabled, CCM disabled, extra options day)
        cam.active_exposure = False
        cam.user_data['waiting_on_image'] = False
        cam.user_data['waiting_on_metadata'] = False
        night_av[constants.NIGHT_NIGHT] = 0  # day

        config['LIBCAMERA']['AWB_ENABLE_DAY'] = True
        config['LIBCAMERA']['AWB_DAY'] = 'auto'
        config['LIBCAMERA']['CCM_DISABLE_DAY'] = True
        config['LIBCAMERA']['EXTRA_OPTIONS_DAY'] = '--custom 123'
        cam.setCcdExposure(exposure=0.01, gain=1.0, binning=99)  # binning 99 triggers BinModeException

        # Night with AWB disabled
        night_av[constants.NIGHT_NIGHT] = 1
        config['LIBCAMERA']['AWB_ENABLE'] = False
        cam.active_exposure = False
        cam.setCcdExposure(exposure=0.01, gain=1.0, binning=1)

        # Tempfile OSError
        with patch('tempfile.NamedTemporaryFile', side_effect=OSError('no temp')):
            cam.active_exposure = False
            cam.setCcdExposure(exposure=0.01, gain=1.0, binning=1)

        # Sync exposure execution
        cam.active_exposure = False
        def fake_publish(*args, **kwargs):
            cam.user_data['waiting_on_metadata'] = False
            cam.user_data['waiting_on_image'] = False

        mock_client.publish.side_effect = fake_publish
        with patch.object(cam, '_processMetadata'), patch.object(cam, '_queueImage'):
            cam.setCcdExposure(exposure=0.01, gain=1.0, binning=1, sync=True)
        mock_client.publish.side_effect = None

        # Invalid image type exception
        config['LIBCAMERA']['IMAGE_FILE_TYPE_DAY'] = 'invalid'
        night_av[constants.NIGHT_NIGHT] = 0
        cam.active_exposure = False
        with pytest.raises(Exception, match='Invalid image type'):
            cam.setCcdExposure(exposure=0.01, gain=1.0, binning=1)

        # Abort exposure
        cam.active_exposure = True
        cam.abortCcdExposure()
        assert cam.active_exposure is False


def test_libcamera_mqtt_callbacks_and_messages(flask_app, tmp_path):
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client), \
         patch('shutil.which', return_value='/usr/bin/rpicam-still'):

        config = {
            'LIBCAMERA': {
                'MQTT_IMAGE_TOPIC': 'cam/img',
                'MQTT_METADATA_TOPIC': 'cam/meta',
            }
        }
        cam = IndiClientLibCameraMqttGeneric(
            config, image_q, position_av, exposure_av, gain_av, binning_av, night_av
        )
        cam.current_metadata_file_p = tmp_path / "meta.json"
        cam.current_exposure_file_p = tmp_path / "img.jpg"

        # on_connect success and failure
        rc_ok = MagicMock(is_failure=False)
        cam.on_connect(mock_client, {}, {}, rc_ok, None)
        assert mock_client.subscribe.call_count == 2

        rc_fail = MagicMock(is_failure=True)
        cam.on_connect(mock_client, {}, {}, rc_fail, None)

        # on_subscribe success and failure
        cam.on_subscribe(mock_client, {}, 1, [MagicMock(is_failure=False, value=0)], None)
        cam.on_subscribe(mock_client, {}, 2, [MagicMock(is_failure=True)], None)

        # on_unsubscribe
        cam.on_unsubscribe(mock_client, {}, 1, [], None)
        cam.on_unsubscribe(mock_client, {}, 2, [MagicMock(is_failure=True)], None)

        # on_publish
        cam.on_publish(mock_client, {}, 1, 0, None)

        # on_message - metadata valid
        msg_meta = MagicMock(topic='cam/meta', payload=b'{"exposure": 1000}')
        userdata = {'waiting_on_metadata': True, 'waiting_on_image': True}
        cam.on_message(mock_client, userdata, msg_meta)
        assert userdata['waiting_on_metadata'] is False
        assert cam.current_metadata_file_p.exists()

        # on_message - metadata corrupt json
        msg_meta_corrupt = MagicMock(topic='cam/meta', payload=b'not json')
        cam.on_message(mock_client, userdata, msg_meta_corrupt)

        # on_message - image data
        msg_img = MagicMock(topic='cam/img', payload=b'\xff\xd8\xffdummy')
        cam.on_message(mock_client, userdata, msg_img)
        assert userdata['waiting_on_image'] is False
        assert cam.current_exposure_file_p.read_bytes() == b'\xff\xd8\xffdummy'

        # on_message - unknown topic
        msg_unknown = MagicMock(topic='cam/other', payload=b'')
        cam.on_message(mock_client, userdata, msg_unknown)

        # getCcdExposureStatus when waiting flags are cleared and active_exposure is True
        cam.active_exposure = True
        cam.exposureStartTime = 100.0
        with patch.object(cam, '_processMetadata') as mock_meta, \
             patch.object(cam, '_queueImage') as mock_queue:
            ready, status = cam.getCcdExposureStatus()
            assert ready is True
            assert status == 'READY'
            mock_meta.assert_called_once()
            mock_queue.assert_called_once()


def test_libcamera_mqtt_subclasses(flask_app):
    image_q = Queue()
    position_av = Array('d', [0.0] * 5)
    exposure_av = Array('f', [-1.0] * 7)
    gain_av = Array('f', [-1.0] * 10)
    binning_av = Array('i', [1] * 6)
    night_av = Array('i', [1, 0])

    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client), \
         patch('shutil.which', return_value='/usr/bin/rpicam-still'):

        config = {}
        imx477 = IndiClientLibCameraImx477Mqtt(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        imx477.findCcd()
        assert imx477.camera_info['width'] == 4056
        imx477.setCcdExposure(0.1, 1.0, 2)  # exercises binmode_options[2]

        imx378 = IndiClientLibCameraImx378Mqtt(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        imx378.findCcd()
        assert imx378.camera_info['width'] == 4056

        imx708 = IndiClientLibCameraImx708Mqtt(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        imx708.findCcd()
        assert imx708.camera_info['width'] == 4608

        owlsight = IndiClientLibCameraOv64a40OwlSightMqtt(config, image_q, position_av, exposure_av, gain_av, binning_av, night_av)
        owlsight.findCcd()
        assert owlsight.camera_info['width'] == 9152
