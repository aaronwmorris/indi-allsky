#!/usr/bin/env python3

import os
import sys
import argparse
import logging
import time
import tempfile
from pathlib import Path
import subprocess


logging.basicConfig(level=logging.INFO)
logger = logging



class TimelapseGenerator(object):
    FFMPEG_FRAMERATE = 25
    FFMPEG_BITRATE = '2500k'


    def __init__(self):
        pass


    def main(self, outfile, inputdir):
        outfile_p = Path(outfile)
        inputdir_p = Path(inputdir)

        if outfile_p.exists():
            logger.error('File already exists: %s', outfile_p)
            sys.exit(1)

        if not inputdir_p.exists():
            logger.error('Directory does not exist: %s', inputdir_p)
            sys.exit(1)


        file_list = list()
        self.getFolderFilesByExt(inputdir_p, file_list)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)

        logger.warning('Found %d files for timelapse', len(file_list_ordered))


        seqfolder = tempfile.TemporaryDirectory()
        p_seqfolder = Path(seqfolder.name)


        for i, f in enumerate(file_list_ordered):
            p_symlink = p_seqfolder.joinpath('{0:05d}.{1:s}'.format(i, 'jpg'))
            p_symlink.symlink_to(f)


        processing_start = time.time()

        cmd = [
            'ffmpeg',
            '-y',
            '-f', 'image2',
            '-r', '{0:d}'.format(self.FFMPEG_FRAMERATE),
            '-i', '{0:s}/%05d.{1:s}'.format(str(p_seqfolder), 'jpg'),
            '-c:v', 'libx264',
            '-b:v', '{0:s}'.format(self.FFMPEG_BITRATE),
            #'-preset', 'medium',
            #'-crf', '23',
            '-pix_fmt', 'yuv420p',
            '{0:s}'.format(str(outfile_p)),
        ]

        ffmpeg_subproc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=lambda: os.nice(19),
        )


        processing_elapsed_s = time.time() - processing_start
        logger.warning('Total keogram processing in %0.1f s', processing_elapsed_s)

        logger.info('FFMPEG output: %s', ffmpeg_subproc.stdout)

        # delete all existing symlinks and sequence folder
        seqfolder.cleanup()



    def getFolderFilesByExt(self, folder, file_list, extension_list=None):
        if not extension_list:
            extension_list = ['jpg']

        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputdir',
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
    tg.main(args.output, args.inputdir)

