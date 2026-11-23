import copy
import json
import multiprocessing
from multiprocessing.reduction import ForkingPickler
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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
os.environ['INDI_ALLSKY_LOG_TARGET'] = 'stderr'

if 'forkserver' in multiprocessing.get_all_start_methods():
    multiprocessing.set_start_method('forkserver', force=True)

from indi_allsky.capture import CaptureWorker  # noqa: E402
from indi_allsky.config import IndiAllSkyConfig  # noqa: E402
from indi_allsky.image import ImageWorker  # noqa: E402
from indi_allsky.sensor import SensorWorker  # noqa: E402
from indi_allsky.video import VideoWorker  # noqa: E402
from indi_allsky.worker_init import configure_worker_logging  # noqa: E402


class TestForkserverWorkers(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        try:
            Path(_TMP_FLASK_CFG.name).unlink()
        except OSError:
            pass

    def _minimal_config(self):
        cfg = copy.deepcopy(IndiAllSkyConfig._base_config)
        cfg['IMAGE_FOLDER'] = '/tmp'
        cfg['VARLIB_FOLDER'] = '/tmp'
        return cfg

    def test_configure_worker_logging(self):
        logger = configure_worker_logging('stderr')
        self.assertTrue(len(logger.handlers) >= 1)
        with self.assertRaises(ValueError):
            configure_worker_logging('invalid_target')

    def test_rawpy_not_imported_with_processing(self):
        self.assertNotIn('rawpy', sys.modules)

    def test_all_workers_are_picklable_for_forkserver(self):
        cfg = self._minimal_config()
        q = multiprocessing.Queue()
        arr_d = multiprocessing.Array('d', [0.0] * 10)
        arr_u = multiprocessing.Array('d', [0.0] * 120)
        arr_i = multiprocessing.Array('i', [0] * 10)

        workers = [
            CaptureWorker(1, cfg, q, q, q, q, q, arr_d, arr_i, arr_i, arr_i, arr_d, arr_u, arr_i, arr_d),
            ImageWorker(1, cfg, q, q, q, arr_d, arr_i, arr_i, arr_i, arr_d, arr_u, arr_i, arr_d),
            VideoWorker(1, cfg, q, q, q, arr_i, arr_i),
            SensorWorker(1, cfg, q, q, arr_d, arr_u, arr_d, arr_i),
        ]

        with patch('multiprocessing.context.assert_spawning'), patch('multiprocessing.sharedctypes.assert_spawning'):
            for worker in workers:
                state = {k: v for k, v in worker.__dict__.items() if k != '_config'}
                payload = ForkingPickler.dumps(state)
                self.assertIsInstance(payload, (bytes, memoryview))
                self.assertGreater(len(payload), 0)

    def test_image_worker_runs_and_stops_under_forkserver(self):
        if 'forkserver' not in multiprocessing.get_all_start_methods():
            self.skipTest('forkserver not available on this platform')

        cfg = self._minimal_config()
        error_q = multiprocessing.Queue()
        image_q = multiprocessing.Queue()
        upload_q = multiprocessing.Queue()
        arr_d = multiprocessing.Array('d', [0.0] * 10)
        arr_u = multiprocessing.Array('d', [0.0] * 120)
        arr_i = multiprocessing.Array('i', [0] * 10)

        worker = ImageWorker(
            1,
            cfg,
            error_q,
            image_q,
            upload_q,
            arr_d,
            arr_i,
            arr_i,
            arr_i,
            arr_d,
            arr_u,
            arr_i,
            arr_d,
        )
        worker.start()
        image_q.put({'stop': True})
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker.exitcode, 0)
        self.assertTrue(error_q.empty())


if __name__ == '__main__':
    unittest.main()
