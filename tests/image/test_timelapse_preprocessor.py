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


def test_preprocessor_wrap_keogram_formats_and_branches(tmp_path):
    # Scratch directory will be automatically created since it does not exist
    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'png',
        'IMAGE_FILE_COMPRESSION': {'jpg': 80, 'png': 6},
        'TIMELAPSE': {
            'IMAGE_CIRCLE': 50,
            'KEOGRAM_RATIO': 0.1,  # Force resize since 20 / 50 = 0.4 > 0.1
        },
        'IMAGE_BORDER': {'TOP': 10, 'LEFT': 4, 'RIGHT': 2, 'BOTTOM': 6},
        'LENS_OFFSET_X': 2,
        'LENS_OFFSET_Y': -2,
    }

    # 1. Test keogram as JPG
    keogram_jpg = tmp_path / "keogram.jpg"
    keogram_data = np.full((30, 80, 3), 100, dtype=np.uint8)
    cv2.imwrite(str(keogram_jpg), keogram_data)

    # Frame with odd dimensions to trigger mod_width/mod_height crop
    frame_jpg = tmp_path / "frame1.jpg"
    frame_data = np.full((121, 123, 3), 50, dtype=np.uint8)
    cv2.imwrite(str(frame_jpg), frame_data)

    proc = PreProcessorWrapKeogram(config)
    proc.keogram = keogram_jpg
    proc.pre_scale = 50  # Test pre_scale < 100

    proc.main([frame_jpg])
    assert (proc.seqfolder / "00000.png").exists()

    # 2. Test keogram with Pillow fallback (e.g. TIFF)
    keogram_tif = tmp_path / "keogram.tif"
    Image.fromarray(keogram_data).save(str(keogram_tif))

    # Test output format webp
    config['IMAGE_FILE_TYPE'] = 'webp'
    proc2 = PreProcessorWrapKeogram(config)
    proc2.keogram = keogram_tif
    proc2.pre_scale = 100

    frame_png = tmp_path / "frame2.png"
    cv2.imwrite(str(frame_png), frame_data)
    proc2.main([frame_png])
    assert (proc2.seqfolder / "00000.webp").exists()

    # 3. Test output format tif and frame with Pillow fallback
    config['IMAGE_FILE_TYPE'] = 'tif'
    proc3 = PreProcessorWrapKeogram(config)
    proc3.keogram = keogram_jpg
    proc3.pre_scale = 100

    frame_tif = tmp_path / "frame3.tif"
    Image.fromarray(frame_data).save(str(frame_tif))
    proc3.main([frame_tif])
    assert (proc3.seqfolder / "00000.tif").exists()

    # 4. Test unsupported output format
    config['IMAGE_FILE_TYPE'] = 'bmp'
    proc4 = PreProcessorWrapKeogram(config)
    proc4.keogram = keogram_jpg
    with pytest.raises(Exception, match='Unknown file type'):
        proc4.main([frame_jpg])


def test_preprocessor_wrap_keogram_errors(tmp_path):
    config = {
        'IMAGE_FOLDER': str(tmp_path),
        'IMAGE_FILE_TYPE': 'jpg',
        'IMAGE_FILE_COMPRESSION': {'jpg': 80, 'png': 6},
        'TIMELAPSE': {
            'IMAGE_CIRCLE': 100,
            'KEOGRAM_RATIO': 0.5,
        },
        'LENS_OFFSET_X': 0,
        'LENS_OFFSET_Y': 0,
    }

    # Invalid PNG keogram decode failure
    bad_keogram_png = tmp_path / "bad_keogram.png"
    bad_keogram_png.write_bytes(b"not an image")
    proc = PreProcessorWrapKeogram(config)
    proc.keogram = bad_keogram_png
    with pytest.raises(Exception, match='Failed to decode keogram'):
        proc.main([tmp_path / "dummy.jpg"])

    # Valid keogram, but invalid frame reads
    valid_keogram = tmp_path / "keogram.png"
    cv2.imwrite(str(valid_keogram), np.full((20, 50, 3), 120, dtype=np.uint8))
    proc.keogram = valid_keogram

    bad_frame_jpg = tmp_path / "bad.jpg"
    bad_frame_jpg.write_bytes(b"not a valid jpeg")

    bad_frame_png = tmp_path / "bad.png"
    bad_frame_png.write_bytes(b"not a valid png")

    bad_frame_tif = tmp_path / "bad.tif"
    bad_frame_tif.write_bytes(b"not a valid tif")

    # These should log errors and safely return without crashing
    proc.main([bad_frame_jpg, bad_frame_png, bad_frame_tif])
    # image_count was not incremented
    assert proc.image_count == 0

