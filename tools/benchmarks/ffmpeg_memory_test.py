#!/usr/bin/env python3

#import tempfile
from pathlib import Path
import numpy
import cv2
import logging


### 1k
WIDTH, HEIGHT = 1280, 960
#WIDTH, HEIGHT = 1920, 1080

### 4k
#WIDTH, HEIGHT = 3840, 2160
#WIDTH, HEIGHT = 3008, 3008
#WIDTH, HEIGHT = 4056, 3040

### 8k
#WIDTH, HEIGHT = 6224, 4168

### insanity
#WIDTH, HEIGHT = 9152, 6944


logging.basicConfig(level=logging.INFO)
logger = logging


class FfmpegMemoryTest(object):

    codec = 'libx264'
    framerate = 25
    bitrate = '10000k'
    vf_scale = ''
    ffmpeg_extra_options = ''


    def __init__(self):
        cwd = Path(__file__).parent.absolute()

        #tmp_img_dir = tempfile.TemporaryDirectory(dir=cwd)    # context manager automatically deletes files when finished
        #self.tmp_img_dir_p = Path(tmp_img_dir.name)

        self.tmp_img_dir_p = cwd.joinpath('ffmpeg_memory')

        if not self.tmp_img_dir_p.is_dir():
            self.tmp_img_dir_p.mkdir()


    def main(self):
        for x in range(250):
            random_rgb = numpy.random.randint(255, size=(HEIGHT, WIDTH, 3), dtype=numpy.uint8)

            image_file_p = self.tmp_img_dir_p.joinpath('{0:05d}.jpg'.format(x))

            logger.info('File: %s', image_file_p)
            cv2.imwrite(str(image_file_p), random_rgb, [cv2.IMWRITE_JPEG_QUALITY, 25])

        cmd = ['ffmpeg']

        # add general extra options
        if self.codec in ['h264_qsv']:
            cmd.extend(['-init_hw_device', 'qsv=hw', '-filter_hw_device', 'hw'])

        cmd.extend([
            '-y',
            '-loglevel', 'level+warning',
            '-r', '{0:0.2f}'.format(self.framerate),
            '-f', 'image2',
            #'-start_number', '0',
            #'-pattern_type', 'glob',
            '-i', '"{0:s}/%05d.jpg"'.format(str(self.tmp_img_dir_p)),
            '-vcodec', '{0:s}'.format(self.codec),
            '-b:v', '{0:s}'.format(self.bitrate),
            #'-filter:v', 'setpts=50*PTS',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
        ])

        # add extra options
        if self.ffmpeg_extra_options:
            cmd.extend(self.ffmpeg_extra_options.split(' '))


        video_file_p = self.tmp_img_dir_p.joinpath('_deleteme.mp4')

        # finally add filename
        cmd.append('{0:s}'.format(str(video_file_p)))

        logger.info('FFmpeg command: %s', ' '.join(cmd))


if __name__ == "__main__":
    FfmpegMemoryTest().main()

