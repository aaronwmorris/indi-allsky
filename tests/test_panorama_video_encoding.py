import json
import shutil
import subprocess

import pytest

from indi_allsky.panorama import panoramaVideoOptions


@pytest.mark.parametrize('level_option', ['-level', '-level:v', '-level:v:0'])
def test_panorama_crop_custom_filters_and_codec_options(level_option):
    extra = ['-preset', 'fast', level_option, '3.1', '-filter:v', 'hflip']
    options = panoramaVideoOptions('libx264', 'crop=320:200', extra)
    assert options[0] == '-vf'
    assert options[1].startswith('crop=320:200,hflip,scale=')
    assert options[1].endswith(',setsar=1')
    assert options[2:] == ['-preset', 'fast']
    assert panoramaVideoOptions('libx265', '', extra)[2:] == ['-preset', 'fast', level_option, '3.1']


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg tools required')
@pytest.mark.parametrize('source_size,expected_size', [
    ('11780x1874', (1920, 306)),
    ('640x1600', (432, 1080)),
    ('322x99', (322, 98)),
])
def test_panorama_video_limits_size_without_cropping_or_enlarging(tmp_path, source_size, expected_size):
    video = tmp_path / 'panorama.mp4'
    options = panoramaVideoOptions('libx264', '', ['-level', '3.1', '-preset', 'ultrafast'])
    subprocess.run([
        'ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        f'testsrc=size={source_size}:rate=25', *options, '-frames:v', '3',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video),
    ], check=True)
    output = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,sample_aspect_ratio,nb_frames', '-of', 'json', str(video)])
    stream = json.loads(output)['streams'][0]
    assert (stream['width'], stream['height']) == expected_size
    assert stream['sample_aspect_ratio'] == '1:1'
    # All three generated pictures must actually change when decoded.
    hashes = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(video),
        '-f', 'framemd5', '-']).decode().splitlines()
    assert len({line.rsplit(',', 1)[-1].strip() for line in hashes if not line.startswith('#')}) == 3
