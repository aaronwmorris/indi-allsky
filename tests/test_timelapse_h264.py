"""Regression coverage for libx264 startup rate control and hardware playback."""
import json
import shutil
import subprocess

import pytest

from indi_allsky.timelapse import TimelapseGenerator, _x264_timelapse_options


def test_legacy_default_uses_configured_bitrate_and_framerate():
    assert _x264_timelapse_options('9000k', 30, ['-level', '3.1']) == [
        '-maxrate', '9000k', '-bufsize', '9000k', '-refs', '1', '-g', '60',
        '-x264-params', 'mvrange=512',
    ]


def test_camera_settings_are_already_complete():
    options = '-maxrate 30000k -bufsize 30000k -refs 1 -g 50 -x264-params mvrange=512'.split()
    assert _x264_timelapse_options('30000k', 25, options) == options


@pytest.mark.parametrize('flag,value', [
    ('-crf:v:0', '17'), ('-qp', '0'), ('-pass', '2'),
    ('-x264-params', 'crf=19'), ('-x264opts', 'vbv-maxrate=500:vbv-bufsize=1000'),
])
def test_advanced_rate_control_is_left_to_the_user(flag, value):
    result = _x264_timelapse_options('5000k', 25, [flag, value])
    assert '-maxrate' not in result
    assert result.count('-bufsize') == int(flag == '-bufsize')
    supplied = result[result.index(flag) + 1]
    assert supplied == (value + ':mvrange=512' if flag == '-x264-params' else value)


def test_partial_vbv_setting_keeps_its_value_and_completes_the_other_half():
    result = _x264_timelapse_options('5000k', 25, ['-maxrate:v', '8M'])
    assert result[:2] == ['-bufsize', '8M'] and '-maxrate' not in result
    result = _x264_timelapse_options('5000k', 25, ['-x264-params', 'vbv-maxrate=7000'])
    assert result[:2] == ['-bufsize', '7000k'] and '-maxrate' not in result
    result = _x264_timelapse_options('5000k', 25, ['-bufsize', '2500k'])
    assert result[:2] == ['-maxrate', '5000k'] and result.count('-bufsize') == 1


def test_use_effective_bitrate_and_keep_custom_reference_gop_and_native_options():
    options = ['-b:v:0', '4M', '-level:v', '5.1', '-refs:v', '2',
               '-x264-params:v:0', 'keyint=75:aq-strength=0.7']
    assert _x264_timelapse_options('5000k', 25, options) == [
        '-maxrate', '4M', '-bufsize', '4M', *options[:-1], 'keyint=75:aq-strength=0.7:mvrange=512',
    ]
    options = ['-g', '15', '-x264opts', 'bitrate=1800:ref=4:mvrange=256']
    assert _x264_timelapse_options('5000k', 25, options) == [
        '-maxrate', '1800k', '-bufsize', '1800k', *options,
    ]


def test_overridden_output_codec_has_no_x264_arguments():
    opts = ['-c:v:0', 'libx265', '-preset', 'fast']
    assert _x264_timelapse_options('5000k', 25, opts) == opts


@pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='ffmpeg tools required')
def test_full_resolution_timelapse_chooses_a_valid_level_and_decodes(tmp_path):
    from PIL import Image

    source = tmp_path / 'sky.jpg'
    Image.new('RGB', (3830, 3040), (17, 23, 35)).save(source)
    movie = tmp_path / 'sky.mp4'
    generator = TimelapseGenerator({'IMAGE_FILE_TYPE': 'jpg'})
    generator.ffmpeg_bin = shutil.which('ffmpeg')
    generator.bitrate = '30000k'
    generator.ffmpeg_extra_options = '-level 3.1'
    generator.generate(movie, [source, source, source], preserve_order=True)
    output = subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                      '-show_entries', 'stream=width,height,level,nb_read_frames', '-of', 'json', movie])
    stream = json.loads(output)['streams'][0]
    assert (stream['width'], stream['height'], stream['nb_read_frames']) == (3830, 3040, '3')
    assert stream['level'] >= 60
