import ast
from datetime import date, datetime, timezone
import logging
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace

import cv2
import numpy

from indi_allsky import constants


def test_regular_images_survive_the_repeated_local_second(tmp_path, monkeypatch):
    # Load the production writer and directory selection without starting capture workers.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/image.py'
    worker_class = next(node for node in ast.parse(path.read_text()).body
                        if isinstance(node, ast.ClassDef) and node.name == 'ImageWorker')
    methods = [node for node in worker_class.body
               if isinstance(node, ast.FunctionDef) and node.name in ('write_img', '_getImageFolder')]
    scope = dict(Path=Path, cv2=cv2, tempfile=tempfile, shutil=shutil, constants=constants,
                 logger=logging.getLogger('indi_allsky'))
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), scope)
    worker = type('Worker', (), {method.name: scope[method.name] for method in methods})()
    worker.image_dir = tmp_path
    worker.filename_t = 'ccd{0:d}_{1:s}.{2:s}'
    worker.config = {'IMAGE_FILE_TYPE': 'png', 'IMAGE_FILE_COMPRESSION': {'png': 1}, 'DAYTIME_CAPTURE': True}
    worker.night_av = [True]
    camera = SimpleNamespace(uuid='test-camera')

    timestamps = [int(datetime(2026, 10, 25, hour, 30, 12, tzinfo=timezone.utc).timestamp())
                  for hour in (0, 1)]
    colors = [35, 190]
    try:
        with monkeypatch.context() as local:
            local.setenv('TZ', 'Europe/Berlin')
            time.tzset()
            for fold, (stamp, color) in enumerate(zip(timestamps, colors)):
                # This is how the worker converts the original POSIX capture time.
                exp_date = datetime.fromtimestamp(stamp)
                assert exp_date.fold == fold
                assert exp_date.strftime('%Y%m%d_%H%M%S') == '20261025_023012'
                frame = SimpleNamespace(exp_date=exp_date, day_date=date(2026, 10, 24), camera_id=1)
                latest, saved = worker.write_img(numpy.full((4, 4, 3), color, dtype=numpy.uint8), frame, camera)
                expected = tmp_path / 'ccd_test-camera/exposures/20261024/night/25_02'
                name = 'ccd1_20261025_023012' + (f'_{stamp}' if fold else '') + '.png'
                assert saved == expected / name
                assert latest == tmp_path / 'latest.png'
    finally:
        time.tzset()

    exposures = sorted(expected.glob('*.png'))
    assert len(exposures) == 2
    assert [cv2.imread(str(p))[0, 0, 0] for p in exposures] == colors
    assert cv2.imread(str(latest))[0, 0, 0] == colors[-1]
