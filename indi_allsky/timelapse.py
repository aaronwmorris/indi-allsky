import os
import time
import tempfile
from pathlib import Path
import subprocess
import logging

from .exceptions import TimelapseException


logger = logging.getLogger('indi_allsky')



class TimelapseGenerator(object):

    def __init__(self, config):
        self.config = config

        self.seqfolder = tempfile.TemporaryDirectory(suffix='_timelapse')  # context manager automatically deletes files when finished
        self.seqfolder_p = Path(self.seqfolder.name)

        #seqfolder = tempfile.mkdtemp(suffix='_timelapse')  # testing
        #self.seqfolder_p = Path(seqfolder)


    def generate(self, video_file, file_list, skip_frames=0):
        video_file_p = Path(video_file)

        # Exclude empty files
        file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

        # Sort by timestamp
        file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        if skip_frames:
            logger.warning('Skipping %d frames for timelapse', skip_frames)
            file_list_ordered = file_list_ordered[skip_frames:]

        for i, f in enumerate(file_list_ordered):
            # the symlink files must start at index 0 or ffmpeg will fail
            p_symlink = self.seqfolder_p.joinpath('{0:05d}.{1:s}'.format(i, self.config['IMAGE_FILE_TYPE']))
            p_symlink.symlink_to(f)


        start = time.time()

        cmd = [
            'ffmpeg',
            '-y',
            '-loglevel', 'level+warning',
            '-f', 'image2',
            '-r', '{0:d}'.format(self.config['FFMPEG_FRAMERATE']),
            #'-start_number', '0',
            #'-pattern_type', 'glob',
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


        # add extra options
        ffmpeg_extra_options = self.config.get('FFMPEG_EXTRA_OPTIONS')
        if ffmpeg_extra_options:
            cmd.extend(ffmpeg_extra_options.split(' '))


        # finally add filename
        cmd.append('{0:s}'.format(str(video_file_p)))

        logger.info('FFmpeg command: %s', ' '.join(cmd))

        try:
            ffmpeg_subproc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=lambda: os.nice(19),
                check=True
            )
            elapsed_s = time.time() - start
            logger.info('Timelapse generated in %0.4f s', elapsed_s)

            logger.info('FFMPEG output: %s', ffmpeg_subproc.stdout)
        except subprocess.CalledProcessError as e:
            elapsed_s = time.time() - start

            logger.info('FFMPEG ran for %0.4f s', elapsed_s)
            logger.error('FFMPEG failed to generate timelapse, return code: %d', e.returncode)
            logger.error('FFMPEG output: %s', e.stdout)

            # Check if video file was created
            if video_file_p.is_file():
                logger.error('FFMPEG created broken video file, cleaning up')
                video_file_p.unlink()

            raise TimelapseException('FFMPEG return code %d', e.returncode)


        # set default permissions
        video_file_p.chmod(0o644)

