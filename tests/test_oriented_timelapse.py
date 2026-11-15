"""Decode real movies to check that a changed camera roll does not move north."""
import json
import os
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from indi_allsky.timelapse import TimelapseGenerator


pytestmark = pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')),
                                reason='ffmpeg and ffprobe required')


@pytest.mark.parametrize('processor,extension,preserve_order', [
    ('standard', 'png', False),    # nightly movie, chronological input mtimes
    ('standard', 'jpg', True),     # mini movie, supplied capture order
    ('wrap_keogram', 'png', False),
])
def test_each_archived_pose_places_north_up_and_east_left(tmp_path, processor, extension, preserve_order):
    width = 128
    center = width // 2
    config = {'IMAGE_FOLDER': str(tmp_path), 'IMAGE_FILE_TYPE': extension,
              'IMAGE_FILE_COMPRESSION': {'png': 1, 'jpg': 95},
              'TIMELAPSE': {'IMAGE_CIRCLE': width}}
    generator = TimelapseGenerator(config, pre_processor_class=processor)
    generator.ffmpeg_bin = shutil.which('ffmpeg')
    paths = []
    # Coordinates of the same two sky directions for each independent camera roll.
    poses = [(0, (64, 32), (32, 64)), (90, (96, 64), (64, 32)), (180, (64, 96), (96, 64))]
    for index, (roll, north, east) in enumerate(poses):
        image = np.zeros((width, width, 3), np.uint8)
        cv2.circle(image, north, 5, (0, 250, 0), -1)
        cv2.circle(image, east, 5, (0, 0, 250), -1)
        cv2.circle(image, (center, center), 6, (60 + index * 80,) * 3, -1)
        path = tmp_path / f'{index}.{extension}'
        assert cv2.imwrite(str(path), image)
        os.utime(path, (1700000000 + index, 1700000000 + index))
        paths.append(path)
        generator.pre_processor.frame_alignments[path] = {
            'image_size': [width, width],
            'values': {'AZIMUTH_ANGLE': roll, 'IMAGE_CIRCLE_DIAMETER': width,
                       'OFFSET_X': 0, 'OFFSET_Y': 0, 'RADIAL_DISTORTION': 0,
                       'LENS_ALTITUDE': 90, 'POINTING_AZIMUTH': 0},
        }

    if processor == 'wrap_keogram':
        keogram = tmp_path / 'keogram.png'
        assert cv2.imwrite(str(keogram), np.full((10, 48, 3), 25, np.uint8))
        generator.pre_processor.keogram = keogram
    movie = tmp_path / 'session.mp4'
    generator.generate(movie, paths[::-1], preserve_order=preserve_order)

    video = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(movie)]))['streams'][0]
    raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(movie),
                                   '-pix_fmt', 'bgr24', '-f', 'rawvideo', '-'])
    decoded = np.frombuffer(raw, np.uint8).reshape(-1, video['height'], video['width'], 3)
    assert len(decoded) == len(poses)
    cy, cx = video['height'] // 2, video['width'] // 2
    order = [2, 1, 0] if preserve_order else [0, 1, 2]
    for frame, index in zip(decoded, order):
        north = frame[cy-32, cx]
        east = frame[cy, cx-32]
        assert north[1] > 200 and north[0] < 70 and north[2] < 70
        assert east[2] > 200 and east[0] < 70 and east[1] < 70
        assert abs(float(frame[cy, cx].mean()) - (60 + index * 80)) < 10
