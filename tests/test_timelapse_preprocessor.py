import tempfile
from pathlib import Path
import numpy as np
import cv2
import pytest
from PIL import Image

from indi_allsky.timelapse_preprocessor.preProcessorBase import PreProcessorBase
from indi_allsky.timelapse_preprocessor.preProcessorStandard import PreProcessorStandard
from indi_allsky.timelapse_preprocessor.preProcessorWrapKeogram import PreProcessorWrapKeogram


def test_preprocessor_base():
    base = PreProcessorBase({'IMAGE_FOLDER': '/tmp'})
    assert str(base.image_dir) == '/tmp'
    base.keogram = '/tmp/keogram.jpg'
    assert str(base.keogram) == '/tmp/keogram.jpg'
    base.keogram = None
    assert base.keogram is None
    base.pre_scale = 50
    assert base.pre_scale == 50


def test_preprocessor_standard(tmp_path):
    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
    }
    proc = PreProcessorStandard(config)

    # Create dummy images
    img1 = tmp_path / "img1.jpg"
    img2 = tmp_path / "img2.jpg"
    img1.touch()
    img2.touch()

    proc.main([img1, img2])
    # Verify symlinks were created in seqfolder
    assert (proc.seqfolder / "00000.jpg").exists()
    assert (proc.seqfolder / "00001.jpg").exists()


def test_preprocessor_wrap_keogram(tmp_path):
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 80, 'png': 6},
        'TIMELAPSE': {
            'IMAGE_CIRCLE': 100,
            'KEOGRAM_RATIO': 0.2,
        },
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
    }

    # Create a small keogram
    keogram_path = tmp_path / "keogram.png"
    keogram_data = np.full((20, 100, 3), 120, dtype=np.uint8)
    cv2.imwrite(str(keogram_path), keogram_data)

    # Create sample frame
    frame_path = tmp_path / "frame.jpg"
    frame_data = np.full((120, 120, 3), 60, dtype=np.uint8)
    cv2.imwrite(str(frame_path), frame_data)

    proc = PreProcessorWrapKeogram(config)
    proc.keogram = keogram_path
    proc.pre_scale = 100

    proc.main([frame_path])

    # Check that processed frame exists in output folder
    out_file = proc.seqfolder / "00000.jpg"
    assert out_file.exists()
