from datetime import datetime
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

if 'INDI_ALLSKY_FLASK_CONFIG' not in os.environ:
    _tmp_flask_cfg = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    json.dump({
        'SECRET_KEY': 'test-secret-key',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'MIGRATION_FOLDER': 'migrations',
        'INDI_ALLSKY_IMAGE_FOLDER': tempfile.gettempdir(),
        'ADMIN_NETWORKS': ['127.0.0.1/32'],
    }, _tmp_flask_cfg)
    _tmp_flask_cfg.close()
    os.environ['INDI_ALLSKY_FLASK_CONFIG'] = _tmp_flask_cfg.name

from indi_allsky.flask.views import _parse_custom_timelapse_request
from indi_allsky.flask.views import WsControlView
from indi_allsky.video import VideoWorker


class TestParseCustomTimelapseRequest:
    def test_valid_iso_range_ui(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': '1',
                'SOURCE_TYPE': 'standard',
                'START_TIME': '2026-11-22T12:00',
                'END_TIME': '2026-11-23T12:00',
                'FRAMERATE_SELECT': '25',
                'BITRATE_SELECT': '5000k',
                'NOTE': 'Noon to noon',
            },
            require_note=True,
        )
        assert err is None
        assert parsed['camera_id'] == 1
        assert parsed['source_type'] == 'standard'
        assert parsed['start_date'] == '2026-11-22T12:00:00'
        assert parsed['end_date'] == '2026-11-23T12:00:00'
        assert parsed['framerate'] == 25.0
        assert parsed['bitrate'] == '5000k'
        assert parsed['note'] == 'Noon to noon'

    def test_valid_rolling_hours_ws_defaults_note(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'hours': 24,
                'framerate': 10,
            },
            default_camera_id=2,
            require_note=False,
        )
        assert err is None
        assert parsed['camera_id'] == 2
        assert parsed['note'].startswith('Custom ')
        start_dt = datetime.fromisoformat(parsed['start_date'])
        end_dt = datetime.fromisoformat(parsed['end_date'])
        assert abs((end_dt - start_dt).total_seconds() - 24 * 3600) < 5

    def test_rejects_start_after_end(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': 1,
                'start_time': '2026-11-23T12:00:00',
                'end_time': '2026-11-22T12:00:00',
                'note': 'Bad range',
            }
        )
        assert parsed is None
        assert 'before end' in err

    def test_rejects_range_over_7_days(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': 1,
                'start_time': '2026-11-01T00:00:00',
                'end_time': '2026-11-10T00:00:00',
                'note': 'Too long',
            }
        )
        assert parsed is None
        assert '7 days' in err

    def test_rejects_panorama_when_disabled(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': 1,
                'source_type': 'panorama',
                'hours': 6,
                'note': 'Pano',
            },
            fish2pano_enabled=False,
        )
        assert parsed is None
        assert 'Panorama' in err

    def test_rejects_invalid_bitrate_and_missing_note(self):
        parsed, err = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': 1,
                'hours': 6,
                'bitrate': 'invalid',
                'note': 'Test',
            }
        )
        assert parsed is None
        assert 'bitrate' in err.lower()

        parsed2, err2 = _parse_custom_timelapse_request(
            {
                'CAMERA_ID': 1,
                'hours': 6,
                'note': '   ',
            },
            require_note=True,
        )
        assert parsed2 is None
        assert 'description' in err2.lower()


class TestVideoWorkerGenerateCustomVideo:
    def _make_worker(self):
        worker = object.__new__(VideoWorker)
        worker.config = {'FFMPEG_CODEC': 'libx264'}
        return worker

    def test_invalid_date_range_sets_failed(self):
        worker = self._make_worker()
        task = MagicMock()
        worker.generateCustomVideo(
            task,
            camera_id=1,
            start_date='2026-11-23T12:00:00',
            end_date='2026-11-22T12:00:00',
        )
        task.setRunning.assert_called_once()
        task.setFailed.assert_called_once_with('Custom timelapse start_date must be before end_date')

    def test_no_images_sets_failed(self):
        from indi_allsky.flask import create_app
        from indi_allsky.flask.models import IndiAllSkyDbCameraTable
        from indi_allsky.flask.models import IndiAllSkyDbImageTable

        flask_app = create_app()
        worker = self._make_worker()
        task = MagicMock()
        camera = SimpleNamespace(id=1)

        with flask_app.app_context(), \
             patch.object(IndiAllSkyDbCameraTable, 'query') as mock_cam_q, \
             patch.object(IndiAllSkyDbImageTable, 'query') as mock_img_q:
            mock_cam_q.filter.return_value.one.return_value = camera
            q = mock_img_q.join.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value
            q.order_by.return_value.first.return_value = None

            worker.generateCustomVideo(
                task,
                camera_id=1,
                start_date='2026-11-22T12:00:00',
                end_date='2026-11-23T12:00:00',
            )

        task.setFailed.assert_called_once_with('No images found in selected time range')

    def test_valid_range_calls_build_mini_video(self):
        from indi_allsky.flask import create_app
        from indi_allsky.flask.models import IndiAllSkyDbCameraTable
        from indi_allsky.flask.models import IndiAllSkyDbImageTable

        flask_app = create_app()
        worker = self._make_worker()
        worker._buildMiniVideo = MagicMock()
        task = MagicMock()
        camera = SimpleNamespace(id=1)
        first_entry = SimpleNamespace(
            dayDate=datetime(2026, 11, 22).date(),
            night=True,
        )

        with flask_app.app_context(), \
             patch.object(IndiAllSkyDbCameraTable, 'query') as mock_cam_q, \
             patch.object(IndiAllSkyDbImageTable, 'query') as mock_img_q:
            mock_cam_q.filter.return_value.one.return_value = camera
            q = mock_img_q.join.return_value.filter.return_value.filter.return_value.filter.return_value.filter.return_value
            q.order_by.return_value.first.return_value = first_entry

            worker.generateCustomVideo(
                task,
                camera_id=1,
                start_date='2026-11-22T12:00:00',
                end_date='2026-11-23T12:00:00',
                framerate=25,
                bitrate='5000k',
                note='Noon-to-Noon',
            )

        worker._buildMiniVideo.assert_called_once()
        call_kwargs = worker._buildMiniVideo.call_args.kwargs
        assert call_kwargs['filename_prefix'] == 'allsky-customtimelapse'
        assert call_kwargs['use_panorama'] is False
        assert call_kwargs['panorama_params'] is None
        assert call_kwargs['note'] == 'Noon-to-Noon'
        assert call_kwargs['framerate'] == 25.0


class TestWsControlCustomTimelapse:
    def test_ws_control_generate_custom_timelapse_and_get_task_status(self):
        from indi_allsky.flask import create_app
        from indi_allsky.flask.models import IndiAllSkyDbCameraTable
        from indi_allsky.flask.models import IndiAllSkyDbTaskQueueTable

        flask_app = create_app()

        fake_ws = MagicMock()
        fake_ws.receive.side_effect = [
            json.dumps({
                'action': 'generate_custom_timelapse',
                'camera_id': 1,
                'hours': 12,
                'framerate': 20,
                'note': 'WS test',
            }),
            json.dumps({
                'action': 'get_task_status',
                'task_id': 99,
            }),
            None,
        ]

        fake_cam = SimpleNamespace(id=1)
        fake_task = SimpleNamespace(
            id=99,
            queue=SimpleNamespace(name='VIDEO'),
            state=SimpleNamespace(name='SUCCESS'),
            result='Generated timelapse (mini_video_id=7): test.mp4',
        )

        view = object.__new__(WsControlView)
        view.indi_allsky_config = {'WEBSOCKET_API_KEY': 'test-key', 'FISH2PANO': {'ENABLE': False}}

        with flask_app.test_request_context('/ws/control?api_key=test-key'), \
             patch('simple_websocket.Server.accept', return_value=fake_ws), \
             patch('indi_allsky.events.event_manager.register'), \
             patch('indi_allsky.events.event_manager.unregister'), \
             patch.object(IndiAllSkyDbCameraTable, 'query') as mock_cam_q, \
             patch('indi_allsky.flask.views._queue_custom_timelapse', return_value=fake_task) as mock_queue, \
             patch.object(IndiAllSkyDbTaskQueueTable, 'query') as mock_task_q:
            mock_cam_q.filter.return_value.first.return_value = fake_cam
            mock_task_q.filter.return_value.first.return_value = fake_task
            view.dispatch_request()

        mock_queue.assert_called_once()
        sent_payloads = [json.loads(c.args[0]) for c in fake_ws.send.call_args_list]
        assert sent_payloads[0]['event'] == 'connected'
        assert sent_payloads[1]['event'] == 'command_result'
        assert sent_payloads[1]['data']['status'] == 'queued'
        assert sent_payloads[1]['data']['task_id'] == 99
        assert sent_payloads[2]['event'] == 'task_status'
        assert sent_payloads[2]['data']['state'] == 'SUCCESS'
        assert 'mini_video_id=7' in sent_payloads[2]['data']['result']
