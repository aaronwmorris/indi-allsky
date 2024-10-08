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

        self._codec = 'libx264'
        self._framerate = 25
        self._bitrate = '5000k'
        self._vf_scale = ''
        self._ffmpeg_extra_options = ''


    @property
    def codec(self):
        return self._codec

    @codec.setter
    def codec(self, new_codec):
        self._codec = str(new_codec)

    @property
    def framerate(self):
        return self._framerate

    @framerate.setter
    def framerate(self, new_framerate):
        self._framerate = float(new_framerate)

    @property
    def bitrate(self):
        return self._bitrate

    @bitrate.setter
    def bitrate(self, new_bitrate):
        self._bitrate = str(new_bitrate)

    @property
    def vf_scale(self):
        return self._vf_scale

    @vf_scale.setter
    def vf_scale(self, new_vf_scale):
        self._vf_scale = str(new_vf_scale)

    @property
    def ffmpeg_extra_options(self):
        return self._ffmpeg_extra_options

    @ffmpeg_extra_options.setter
    def ffmpeg_extra_options(self, new_ffmpeg_extra_options):
        self._ffmpeg_extra_options = str(new_ffmpeg_extra_options)


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
            '-r', '{0:0.2f}'.format(self.framerate),
            '-f', 'image2',
            #'-start_number', '0',
            #'-pattern_type', 'glob',
            '-i', '{0:s}/%05d.{1:s}'.format(str(self.seqfolder_p), self.config['IMAGE_FILE_TYPE']),
            '-vcodec', '{0:s}'.format(self.codec),
            '-b:v', '{0:s}'.format(self.bitrate),
            #'-filter:v', 'setpts=50*PTS',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
        ]


        # add scaling option if defined
        if self.vf_scale:
            logger.warning('Setting FFMPEG scaling option: %s', self.vf_scale)
            cmd.append('-vf')
            cmd.append('scale={0:s}'.format(self.vf_scale))


        # add extra options
        if self.ffmpeg_extra_options:
            cmd.extend(self.ffmpeg_extra_options.split(' '))


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

