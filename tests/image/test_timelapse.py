from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess
import pytest

from indi_allsky.timelapse import TimelapseGenerator


def test_timelapse_generator_properties():
    config = {
        'IMAGE_FILE_TYPE': 'jpg',
    }
    generator = TimelapseGenerator(config, skip_frames=2, pre_processor_class='standard')

    generator.codec = 'libx264'
    assert generator.codec == 'libx264'

    generator.framerate = 30.0
    assert generator.framerate == 30.0

    generator.bitrate = '8000k'
    assert generator.bitrate == '8000k'

    generator.vf_scale = '1920:1080'
    assert generator.vf_scale == '1920:1080'

    generator.video_filter = 'hqdn3d=1.5:1.5:6:6'
    assert generator.video_filter == 'hqdn3d=1.5:1.5:6:6'

    generator.ffmpeg_extra_options = '-preset fast'
    assert generator.ffmpeg_extra_options == '-preset fast'


def test_timelapse_generate(tmp_path):
    config = {
        'IMAGE_FILE_TYPE': 'jpg',
    }
    generator = TimelapseGenerator(config, skip_frames=0, pre_processor_class='standard')
    generator.vf_scale = '1280:720'

    # Create dummy files
    f1 = tmp_path / "img1.jpg"
    f2 = tmp_path / "img2.jpg"
    f1.write_bytes(b"image1")
    f2.write_bytes(b"image2")

    out_video = tmp_path / "output.mp4"
    out_video.write_bytes(b"mock video output")

    mock_res = subprocess.CompletedProcess(
        args=['ffmpeg'],
        returncode=0,
        stdout=b"ffmpeg version 6.0 output\nframe=2",
    )

    with patch('subprocess.run', return_value=mock_res):
        with patch.object(generator.pre_processor, 'main'):
            generator.pre_processor._seqfolder = tmp_path
            generator.generate(str(out_video), [f1, f2], preserve_order=True)
