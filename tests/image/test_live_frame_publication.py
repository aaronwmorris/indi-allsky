import ast
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from types import SimpleNamespace

import cv2
import numpy
import pytest

from indi_allsky import constants


def image_writer(tmp_path):
    # Load the production writer and directory selection without starting capture workers.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/image.py'
    worker_class = next(node for node in ast.parse(path.read_text()).body
                        if isinstance(node, ast.ClassDef) and node.name == 'ImageWorker')
    methods = [node for node in worker_class.body
               if isinstance(node, ast.FunctionDef) and node.name in ('write_img', '_getImageFolder')]
    scope = dict(Path=Path, cv2=cv2, os=os, time=time, tempfile=tempfile, shutil=shutil, constants=constants,
                 logger=logging.getLogger('indi_allsky'))
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), scope)
    worker = type('Worker', (), {method.name: scope[method.name] for method in methods})()
    worker.health = SimpleNamespace(image_published=SimpleNamespace(value=0), publications=SimpleNamespace(value=0))
    worker.image_dir = tmp_path
    worker.filename_t = 'ccd{0:d}_{1:s}.{2:s}'
    worker.config = {'IMAGE_FILE_TYPE': 'png', 'IMAGE_FILE_COMPRESSION': {'png': 1}, 'DAYTIME_CAPTURE': True}
    worker.night_av = [True]
    return worker


def test_failed_publication_keeps_last_complete_frame(tmp_path, monkeypatch):
    worker = image_writer(tmp_path)
    latest = tmp_path / 'latest.png'
    latest.write_bytes(b'previous complete image')
    data = numpy.full((4, 4, 3), 50, dtype=numpy.uint8)

    def fail(staged, destination):
        assert Path(staged).parent == latest.parent
        assert destination == latest
        assert cv2.imread(str(staged))[0, 0, 0] == 50
        raise OSError('disk error')

    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='disk error'):
        worker.write_img(data, None, None)
    assert latest.read_bytes() == b'previous complete image'
    assert list(tmp_path.glob('.latest-*')) == []
    assert worker.health.publications.value == 0

    monkeypatch.setattr(cv2, 'imwrite', lambda *args: False)
    assert worker.write_img(data, None, None) == (None, None)
    assert latest.read_bytes() == b'previous complete image'
