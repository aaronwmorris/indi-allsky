import json
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import MagicMock

_TMP_FLASK_CFG = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
json.dump(
    {
        'SECRET_KEY': 'test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'INDI_ALLSKY_DOCROOT': '/tmp',
        'MIGRATION_FOLDER': 'migrations',
    },
    _TMP_FLASK_CFG,
)
_TMP_FLASK_CFG.close()
os.environ.setdefault('INDI_ALLSKY_FLASK_CONFIG', _TMP_FLASK_CFG.name)

from indi_allsky.allsky import IndiAllSky, app  # noqa: E402
from indi_allsky.flask import db  # noqa: E402
from indi_allsky.flask.models import (  # noqa: E402
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.video import VideoWorker  # noqa: E402


class TestVideoTaskQueue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        try:
            Path(_TMP_FLASK_CFG.name).unlink()
        except OSError:
            pass

    def setUp(self):
        with app.app_context():
            IndiAllSkyDbTaskQueueTable.query.delete()
            db.session.commit()

    def _make_daemon_stub(self):
        ia = IndiAllSky.__new__(IndiAllSky)
        ia.video_q = queue.Queue()
        ia.misc_q = queue.Queue()
        return ia

    def test_trigger_allsky_map_ping_deduplicates_and_routes_to_misc_q(self):
        ia = self._make_daemon_stub()

        with app.app_context():
            ia._triggerAllskyMapPing()
            ia._triggerAllskyMapPing()
            ia._triggerAllskyMapPing()

            rows = IndiAllSkyDbTaskQueueTable.query.all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].data['action'], 'sendAllskyMapPing')

            self.assertEqual(ia.misc_q.qsize(), 1)
            self.assertEqual(ia.video_q.qsize(), 0)

            # Once the queued task moves to RUNNING, a new ping may be queued.
            rows[0].setRunning()
            ia._triggerAllskyMapPing()
            self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 2)
            self.assertEqual(ia.misc_q.qsize(), 2)

    def test_deduplication_respects_distinct_kwargs(self):
        ia = self._make_daemon_stub()

        with app.app_context():
            ia._enqueueVideoTask('updateAuroraData', kwargs={'camera_id': 1}, target_queue=ia.misc_q)
            ia._enqueueVideoTask('updateAuroraData', kwargs={'camera_id': 1}, target_queue=ia.misc_q)
            ia._enqueueVideoTask('updateAuroraData', kwargs={'camera_id': 2}, target_queue=ia.misc_q)

            self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 2)
            self.assertEqual(ia.misc_q.qsize(), 2)

    def test_backup_database_routes_to_video_q_and_deduplicates(self):
        ia = self._make_daemon_stub()

        with app.app_context():
            ia._backupDatabase()
            ia._backupDatabase()

            self.assertEqual(IndiAllSkyDbTaskQueueTable.query.count(), 1)
            self.assertEqual(ia.video_q.qsize(), 1)
            self.assertEqual(ia.misc_q.qsize(), 0)

    def test_video_worker_misc_task_worker_processes_misc_q(self):
        misc_q = queue.Queue()
        worker = VideoWorker(1, {'IMAGE_FOLDER': '/tmp'}, queue.Queue(), queue.Queue(), queue.Queue(), [0, 0], [1], misc_q=misc_q)
        worker.processTask = MagicMock()

        misc_q.put({'task_id': 42})
        misc_q.put({'stop': True})
        worker._miscTaskWorker()

        worker.processTask.assert_called_once_with({'task_id': 42})

    def test_stale_misc_task_is_expired_and_reenqueued(self):
        from datetime import datetime, timedelta, timezone
        from indi_allsky.flask.models import TaskQueueState

        ia = self._make_daemon_stub()

        with app.app_context():
            first = ia._enqueueVideoTask('sendAllskyMapPing', target_queue=ia.misc_q)
            first.createDate = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=70)
            db.session.commit()

            second = ia._triggerAllskyMapPing()
            self.assertIsNotNone(second)
            db.session.refresh(first)
            self.assertEqual(first.state, TaskQueueState.EXPIRED)
            self.assertEqual(second.state, TaskQueueState.QUEUED)
            self.assertEqual(ia.misc_q.qsize(), 2)


if __name__ == '__main__':
    unittest.main()
