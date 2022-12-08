import os
import time
import tempfile
from pathlib import Path
import subprocess
import logging


logger = logging.getLogger('indi_allsky')



class TimelapseGenerator(object):

    def __init__(self, config):
        self.config = config

        self.seqfolder = tempfile.TemporaryDirectory(suffix='_timelapse')
        self.seqfolder_p = Path(self.seqfolder.name)


    def __del__(self):
        self.cleanup()


    def generate(self, video_file, file_list):
        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        for i, f in enumerate(file_list_ordered):
            p_symlink = self.seqfolder_p.joinpath('{0:05d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            p_symlink.symlink_to(f)


        start = time.time()

        cmd = [
            'ffmpeg',
            '-y',
            '-loglevel', 'level+warning',
            '-f', 'image2',
            '-r', '{0:d}'.format(self.config['FFMPEG_FRAMERATE']),
            '-i', '{0:s}/%05d.{1:s}'.format(str(self.seqfolder_p), self.config['IMAGE_FILE_TYPE']),
            '-vcodec', '{0:s}'.format(self.config['FFMPEG_CODEC']),
            '-b:v', '{0:s}'.format(self.config['FFMPEG_BITRATE']),
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
        ]


        # add scaling option if defined
        if self.config.get('FFMPEG_VFSCALE'):
            logger.warning('Setting FFMPEG scaling option: %s', self.config.get('FFMPEG_VFSCALE'))
            cmd.append('-vf')
            cmd.append('scale={0:s}'.format(self.config.get('FFMPEG_VFSCALE')))


        # finally add filename
        cmd.append('{0:s}'.format(str(video_file)))


        ffmpeg_subproc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=lambda: os.nice(19),
        )

        elapsed_s = time.time() - start
        logger.info('Timelapse generated in %0.4f s', elapsed_s)

        logger.info('FFMPEG output: %s', ffmpeg_subproc.stdout)


    def cleanup(self):
        # delete all existing symlinks and sequence folder
        self.seqfolder.cleanup()

