#!/usr/bin/env python3

import os
import sys
import argparse
import logging
import time
import tempfile
from pathlib import Path
import subprocess


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


    @property
    def input_dir(self):
        return self._input_dir

    @input_dir.setter
    def input_dir(self, new_input_dir):
        self._input_dir = Path(str(new_input_dir)).absolute()


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

        logger.warning('Found %d files for timelapse', len(file_list_ordered))


        seqfolder = tempfile.TemporaryDirectory()
        seqfolder_p = Path(seqfolder.name)


        for i, f in enumerate(file_list_ordered):
            p_symlink = seqfolder_p.joinpath('{0:05d}.{1:s}'.format(i, IMAGE_FILETYPE))
            p_symlink.symlink_to(f)


        processing_start = time.time()

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


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total timelapse processing in %0.1f s', processing_elapsed_s)

        logger.info('FFMPEG output: %s', ffmpeg_subproc.stdout)

        # delete all existing symlinks and sequence folder
        seqfolder.cleanup()


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
        '--output',
        '-o',
        help='output',
        type=str,
        required=True,
    )


    args = argparser.parse_args()

    tg = TimelapseGenerator()
    tg.input_dir = args.input_dir
    tg.main(args.output)

