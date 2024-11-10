#!/usr/bin/env python3

import sys
import os
import time
import tempfile
import argparse
from pathlib import Path
import subprocess
import numpy
import cv2
import PIL
from PIL import Image
import logging


IMAGE_CIRCLE = 1700
OFFSET_X = 30
OFFSET_Y = -20
KEOGRAM_RATIO = 0.15

IMAGE_FILETYPE = 'jpg'


logging.basicConfig(level=logging.INFO)
logger = logging


class TimelapseGenerator(object):

    FFMPEG_CODEC = 'libx264'

    FFMPEG_FRAMERATE = 25

    FFMPEG_BITRATE = '5000k'
    FFMPEG_BITRATE_MAX = '5000k'
    FFMPEG_BITRATE_MIN = '1000k'
    FFMPEG_BITRATE_BUF = '2000k'

    FFMPEG_QSCALE = 25


    def __init__(self):
        self._input_dir = None
        self._outfile = None
        self._keogram = None

        self._keogram_image = None

        self.file_list_ordered_len = 0
        self.image_count = 0


    @property
    def input_dir(self):
        return self._input_dir

    @input_dir.setter
    def input_dir(self, new_input_dir):
        self._input_dir = Path(str(new_input_dir)).absolute()


    @property
    def keogram(self):
        return self._keogram

    @keogram.setter
    def keogram(self, new_keogram):
        self._keogram = Path(str(new_keogram)).absolute()


    @property
    def outfile(self):
        return self._outfile

    @outfile.setter
    def outfile(self, new_outfile):
        self._outfile = Path(str(new_outfile)).absolute()



    def main(self):
        if self.outfile.exists():
            logger.error('File already exists: %s', self.outfile)
            sys.exit(1)

        if not self.input_dir.exists():
            logger.error('Directory does not exist: %s', self.input_dir)
            sys.exit(1)



        file_list = list()
        self.getFolderFilesByExt(self.input_dir, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)

        self.file_list_ordered_len = len(file_list_ordered)
        logger.warning('Found %d files for timelapse', self.file_list_ordered_len)

        seqfolder = tempfile.TemporaryDirectory(dir=self.input_dir.parent, suffix='_timelapse')
        seqfolder_p = Path(seqfolder.name)


        process_start = time.time()

        for i, f in enumerate(file_list_ordered):
            self.standard(i, f, seqfolder_p)
            #self.wrap(i, f, seqfolder_p)

        process_elapsed_s = time.time() - process_start
        logger.info('Pre-processing in %0.4f s (%0.3fs/image)', process_elapsed_s, process_elapsed_s / len(file_list_ordered))


        timelapse_start = time.time()

        cmd = [
            'ffmpeg',
            '-y',

            '-loglevel', 'level+warning',

            '-r', '{0:d}'.format(self.FFMPEG_FRAMERATE),
            '-f', 'image2',

            #'-start_number', '0',
            #'-pattern_type', 'glob',

            '-i', '{0:s}/%05d.{1:s}'.format(str(seqfolder_p), IMAGE_FILETYPE),

            '-vcodec', self.FFMPEG_CODEC,
            #'-c:v', self.FFMPEG_CODEC,

            '-b:v', '{0:s}'.format(self.FFMPEG_BITRATE),
            #'-minrate', '{0:s}'.format(self.FFMPEG_BITRATE_MIN),
            #'-maxrate', '{0:s}'.format(self.FFMPEG_BITRATE_MAX),
            #'-bufsize', '{0:s}'.format(self.FFMPEG_BITRATE_BUF),

            #'-qscale', '{0:d}'.format(self.FFMPEG_QSCALE),

            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',

            '-level', '3.1',  # better compatibility

            '{0:s}'.format(str(self.outfile)),
        ]


        logger.info('Command: %s', ' '.join(cmd))


        try:
            ffmpeg_subproc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=lambda: os.nice(19),
            )
        except subprocess.CalledProcessError as e:
            logger.error('FFMPEG output: %s', e.stdout)
            sys.exit(1)


        timelapse_elapsed_s = time.time() - timelapse_start
        logger.warning('Total timelapse processing in %0.1f s', timelapse_elapsed_s)

        logger.info('FFMPEG output: %s', ffmpeg_subproc.stdout)


    def standard(self, i, f, seqfolder_p):
        p_symlink = seqfolder_p.joinpath('{0:05d}.{1:s}'.format(i, IMAGE_FILETYPE))
        p_symlink.symlink_to(f)


    def wrap(self, i, f, seqfolder_p):
        logger.info('Processing %s', f)


        if isinstance(self._keogram_image, type(None)):
            with Image.open(str(self.keogram)) as img:
                self._keogram_image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)

            keogram_height, keogram_width = self._keogram_image.shape[:2]

            k_ratio_height = keogram_height / IMAGE_CIRCLE
            if k_ratio_height > KEOGRAM_RATIO:
                # resize keogram
                new_k_height = int(IMAGE_CIRCLE * KEOGRAM_RATIO)
                keogram = cv2.resize(self._keogram_image, (keogram_width, new_k_height), interpolation=cv2.INTER_AREA)
                keogram_height = new_k_height


            logger.info('Keogram: %d x %d', keogram_width, keogram_height)

            # flip upside down and backwards
            self._keogram_image = cv2.flip(self._keogram_image, -1)


        keogram = self._keogram_image.copy()
        keogram_height, keogram_width = keogram.shape[:2]

        current_percent = i / self.file_list_ordered_len

        #keogram_line = int(keogram_width * current_percent)
        keogram_line = int(keogram_width * (1 - current_percent))  # backwards
        #logger.info('Line: %d', keogram_line)

        line = numpy.full([keogram_height, 1, 3], 255, dtype=numpy.uint8)
        keogram[0:keogram_height, keogram_line:keogram_line + 1] = line


        try:
            with Image.open(str(f)) as img:
                image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
        except PIL.UnidentifiedImageError:
            logger.error('Unable to read %s', f)
            return


        image_height, image_width = image.shape[:2]
        #logger.info('Image: %d x %d', image_width, image_height)


        if image_width < (IMAGE_CIRCLE + (keogram_height * 2) + abs(OFFSET_X)):
            final_width = IMAGE_CIRCLE + (keogram_height * 2) + abs(OFFSET_X)
        else:
            final_width = image_width

        if image_height < (IMAGE_CIRCLE + (keogram_height * 2) + abs(OFFSET_Y)):
            final_height = IMAGE_CIRCLE + (keogram_height * 2) + abs(OFFSET_Y)
        else:
            final_height = image_height

        #logger.info('Final: %d x %d', final_width, final_height)


        # add black area at the top of the keogram to wrap around center
        d_keogram = numpy.zeros([int((IMAGE_CIRCLE / 2) + keogram_height), keogram_width, 3], dtype=numpy.uint8)
        d_height, d_width = d_keogram.shape[:2]
        d_keogram[d_height - keogram_height:d_height, 0:keogram_width] = keogram


        # add alpha channel for transparency (black area)
        d_keogram_alpha = numpy.zeros([d_height, d_width], dtype=numpy.uint8)
        d_keogram_alpha[d_height - keogram_height:d_height, 0:keogram_width] = 255
        d_keogram = numpy.dstack((d_keogram, d_keogram_alpha))


        # keogram must be sideways (top/down) to wrap
        d_image = cv2.rotate(d_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)


        # wrap the keogram
        wrapped_keogram = cv2.warpPolar(
            d_image,
            (final_height, final_width),  # cv2 reversed (rotated below)
            (int(final_height / 2), int(final_width / 2)),  # reversed
            int((IMAGE_CIRCLE / 2) + keogram_height),
            cv2.WARP_INVERSE_MAP,
        )

        #wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)  # start keogram at top
        wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_CLOCKWISE)  # start keogram at bottom


        # separate layers
        wrapped_keogram_bgr = wrapped_keogram[:, :, :3]
        wrapped_keogram_alpha = (wrapped_keogram[:, :, 3] / 255).astype(numpy.float32)

        # create alpha mask
        alpha_mask = numpy.dstack((
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
        ))


        f_image = numpy.zeros([final_height, final_width, 3], dtype=numpy.uint8)
        f_image[
            int((final_height / 2) - (image_height / 2) + OFFSET_Y):int((final_height / 2) + (image_height / 2) + OFFSET_Y),
            int((final_width / 2) - (image_width / 2) - OFFSET_X):int((final_width / 2) + (image_width / 2) - OFFSET_X),
        ] = image  # recenter the image circle in the new image


        # apply alpha mask
        image_with_keogram = (f_image * (1 - alpha_mask) + wrapped_keogram_bgr * alpha_mask).astype(numpy.uint8)


        mod_height = final_height % 2
        mod_width = final_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_width = final_width - mod_width
            crop_height = final_height - mod_height

            image_with_keogram = image_with_keogram[
                0:crop_height,
                0:crop_width,
            ]


        outfile_p = seqfolder_p.joinpath('{0:05d}.{1:s}'.format(self.image_count, IMAGE_FILETYPE))
        Image.fromarray(cv2.cvtColor(image_with_keogram, cv2.COLOR_BGR2RGB)).save(str(outfile_p), quality=90)

        self.image_count += 1


    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = [IMAGE_FILETYPE]

        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                if item.name in ('thumbnail', 'thumbnails'):
                    # skip thumbnails
                    continue

                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'input_dir',
        help='Input directory',
        type=str,
    )
    argparser.add_argument(
        '--outfile',
        '-o',
        help='outfile',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--keogram',
        '-k',
        help='keogram',
        type=str,
        required=False
    )


    args = argparser.parse_args()

    tg = TimelapseGenerator()
    tg.input_dir = args.input_dir
    tg.outfile = args.outfile
    tg.keogram = args.keogram
    tg.main()

