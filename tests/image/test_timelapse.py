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


from indi_allsky.exceptions import TimelapseException


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

    with patch('subprocess.run', return_value=mock_res) as mock_run:
        with patch.object(generator.pre_processor, 'main') as mock_pre:
            generator.pre_processor._seqfolder = tmp_path
            generator.generate(str(out_video), [f1, f2], preserve_order=True)

            mock_pre.assert_called_once_with([f1, f2])
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert 'ffmpeg' in cmd[0]
            assert '-c:v' in cmd
            assert 'libx264' in cmd
            assert '-vf' in cmd
            assert 'scale=1280:720' in cmd
            assert '-pix_fmt' in cmd
            assert 'yuv420p' in cmd


def test_timelapse_generate_failure_cleans_up(tmp_path):
    config = {'IMAGE_FILE_TYPE': 'jpg'}
    generator = TimelapseGenerator(config, skip_frames=0, pre_processor_class='standard')

    f1 = tmp_path / "img1.jpg"
    f1.write_bytes(b"image1")
    out_video = tmp_path / "output_broken.mp4"
    out_video.write_bytes(b"broken content")

    mock_err = subprocess.CalledProcessError(
        returncode=1,
        cmd=['ffmpeg'],
        output=b"Error: corrupt input",
    )

    with patch('subprocess.run', side_effect=mock_err):
        with patch.object(generator.pre_processor, 'main'):
            generator.pre_processor._seqfolder = tmp_path
            with pytest.raises(TimelapseException):
                generator.generate(str(out_video), [f1], preserve_order=True)

    # Broken video file must be deleted on failure
    assert not out_video.exists()


@pytest.mark.parametrize('codec', ['h264_qsv', 'h264_nvenc', 'h264_vaapi'])
def test_timelapse_codecs_and_filters(tmp_path, monkeypatch, codec):
    monkeypatch.setenv('HOME', str(tmp_path))
    config = {
        'IMAGE_FILE_TYPE': 'jpg',
        'TIMELAPSE': {'FFMPEG_REPORT': True},
    }
    generator = TimelapseGenerator(config, skip_frames=1, pre_processor_class='standard')
    generator.codec = codec
    generator.video_filter = 'hqdn3d'
    generator.ffmpeg_extra_options = '-profile:v high'

    f0 = tmp_path / "img0.jpg"
    f1 = tmp_path / "img1.jpg"
    f_empty = tmp_path / "img_empty.jpg"
    f0.write_bytes(b"content0")
    f1.write_bytes(b"content1")
    f_empty.write_bytes(b"")

    out_video = tmp_path / "output.mp4"
    out_video.write_bytes(b"mock video")
    mock_res = subprocess.CompletedProcess(args=['ffmpeg'], returncode=0, stdout=b"ok")

    with patch('subprocess.run', return_value=mock_res) as mock_run:
        with patch.object(generator.pre_processor, 'main') as mock_pre:
            generator.pre_processor._seqfolder = tmp_path
            generator.generate(str(out_video), [f0, f_empty, f1], preserve_order=False)

            mock_pre.assert_called_once()
            passed_files = mock_pre.call_args[0][0]
            assert f_empty not in passed_files
            assert len(passed_files) == 1  # 2 non-empty minus skip_frames=1
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            env = mock_run.call_args[1]['env']
            assert 'FFREPORT' in env
            assert '-vf' in cmd
            assert 'hqdn3d' in cmd
            assert '-profile:v' in cmd
            if codec == 'h264_qsv':
                assert '-init_hw_device' in cmd

