import os
import re
import time
from pathlib import Path
import subprocess
import tempfile
import logging
from threading import Thread

from . import timelapse_preprocessor
from .exceptions import TimelapseException
from .panorama import panoramaVideoOptions


logger = logging.getLogger('indi_allsky')



def _x264_timelapse_options(bitrate, framerate, options):
    """Supply browser playback defaults while preserving explicit FFmpeg/x264 settings."""
    # Older installs carried this single option as the factory default. At full
    # camera resolution the level must be determined from the actual output.
    options = [] if options == ['-level', '3.1'] else list(options)
    values = {}
    params_index = None
    for i, arg in enumerate(options[:-1]):
        if not arg.startswith('-'):
            continue
        name = re.sub(r'(?::v(?::0)?|:0)$', '', arg)
        if name in ('-vcodec', '-codec'):
            name = '-c'
        elif name == '-vb':
            name = '-b'
        values[name] = options[i + 1]
        if name == '-x264-params':
            params_index = i + 1
    if values.get('-c', 'libx264') != 'libx264':
        return options

    # The two native x264 option lists also take precedence over our defaults.
    native = {}
    for name in ('-x264opts', '-x264-params'):
        for item in values.get(name, '').split(':'):
            key, _, value = item.partition('=')
            native[key.replace('_', '-')] = value

    defaults = []
    rate_options = {'-crf', '-qp', '-q', '-qscale', '-pass', '-minrate'}
    rate_params = {'crf', 'qp', 'pass'}
    if rate_options.isdisjoint(values) and rate_params.isdisjoint(native):
        # FFmpeg rates use bits/s; x264's native bitrate uses kbit/s.
        target = native['bitrate'] + 'k' if 'bitrate' in native else values.get('-b', bitrate)
        if 'vbv-maxrate' in native:
            peak = native['vbv-maxrate'] + 'k'
        elif '-maxrate' in values:
            peak = values['-maxrate']
        else:
            peak = target
            defaults.extend(['-maxrate', peak])
        if '-bufsize' not in values and 'vbv-bufsize' not in native:
            defaults.extend(['-bufsize', peak])
    if '-refs' not in values and {'ref', 'refs'}.isdisjoint(native):
        defaults.extend(['-refs', '1'])
    if '-g' not in values and 'keyint' not in native:
        defaults.extend(['-g', str(max(1, round(2 * framerate)))])
    if {'mvrange', 'mv-range'}.isdisjoint(native):
        # Limiting the motion-vector range avoids VideoToolbox decode failures
        # late in full-resolution movies. Preserve other native x264 options.
        if params_index is None:
            defaults.extend(['-x264-params', 'mvrange=512'])
        else:
            options[params_index] += ':mvrange=512'
    return defaults + options


def _preserves_frame_count(video_filter, extra_options):
    """Only advertise an output total for filters with one output per input."""
    filters = [video_filter] if video_filter else []
    options = iter(extra_options)
    for option in options:
        flag = option.split(':')[0]
        if flag in ('-vf', '-filter'):
            filters.append(next(options, ''))
        elif flag in ('-r', '-fpsmax', '-fps_mode', '-vsync', '-frames', '-vframes', '-filter_complex',
                      '-filter_script', '-filter_complex_script', '-lavfi', '-t', '-to', '-ss', '-progress'):
            return False

    spatial = {'crop', 'scale', 'setsar', 'format', 'hflip', 'vflip', 'transpose', 'split', 'hstack', 'sendcmd'}
    for graph in filters:
        # A chain can start after input labels and a filter can have an @instance name.
        names = re.findall(r'(?:^|[,;])\s*(?:\[[^\]]+\]\s*)*(\w+)(?:@[\w-]+)?\s*(?==|[,;\[]|$)', graph)
        if not names or any(name not in spatial for name in names):
            return False
    return True


class TimelapseGenerator(object):

    ### System default
    ffmpeg_bin = 'ffmpeg'

    ### jellyfin-ffmpeg
    #ffmpeg_bin = '/usr/lib/jellyfin-ffmpeg/ffmpeg'


    def __init__(
        self,
        config,
        skip_frames=0,
        pre_processor_class='standard',
        panorama=False,
        activity=None,
    ):
        self.config = config
        self.skip_frames = skip_frames
        self.panorama = panorama
        self.activity = activity

        self._codec = 'libx264'
        self._framerate = 25
        self._bitrate = '5000k'
        self._vf_scale = ''
        self._video_filter = ''
        self._ffmpeg_extra_options = ''


        pp_class = getattr(timelapse_preprocessor, pre_processor_class)
        self._pre_processor = pp_class(self.config)


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
    def video_filter(self):
        return self._video_filter

    @video_filter.setter
    def video_filter(self, new_video_filter):
        self._video_filter = str(new_video_filter)

    @property
    def ffmpeg_extra_options(self):
        return self._ffmpeg_extra_options

    @ffmpeg_extra_options.setter
    def ffmpeg_extra_options(self, new_ffmpeg_extra_options):
        self._ffmpeg_extra_options = str(new_ffmpeg_extra_options)


    @property
    def pre_processor(self):
        return self._pre_processor


    def generate(self, video_file, file_list, preserve_order=False):
        video_file_p = Path(video_file)

        if preserve_order:
            file_list_ordered = list(file_list)
        else:
            # Exclude empty files
            file_list_nonzero = filter(lambda p: p.stat().st_size != 0, file_list)

            # Sort by timestamp
            file_list_ordered = sorted(file_list_nonzero, key=lambda p: p.stat().st_mtime)


        if self.skip_frames:
            logger.warning('Skipping %d frames for timelapse', self.skip_frames)
            file_list_ordered = file_list_ordered[self.skip_frames:]


        # process images
        stream = None
        frame_count = len(file_list_ordered)
        if getattr(self.pre_processor, 'frame_alignments', None) and hasattr(self.pre_processor, 'encoded_frames'):
            suffix = '.jpg' if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg') else '.png'
            codec = 'mjpeg' if suffix == '.jpg' else 'png'
            source = ['-f', 'image2pipe', '-c:v', codec, '-i', 'pipe:0']
            stream = self.pre_processor.encoded_frames(file_list_ordered, suffix)
        else:
            prepared_count = self.pre_processor.main(file_list_ordered, activity=self.activity)
            if prepared_count is not None:
                frame_count = prepared_count
            source = ['-f', 'image2', '-i', str(self.pre_processor.seqfolder / ('%05d.' + self.config['IMAGE_FILE_TYPE']))]


        start = time.time()

        cmd = [self.ffmpeg_bin]


        # add codec options
        if self.codec in ['h264_qsv']:
            ### Intel QSV
            cmd.extend(['-init_hw_device', 'qsv=hw', '-filter_hw_device', 'hw'])
        elif self.codec in ['h264_nvenc']:
            ### Nvidia NVENC
            #cmd.extend([])  # nothing to add currently
            pass
        elif self.codec in ['h264_vaapi']:
            ### AMD VAAPI
            #cmd.extend([])  # nothing to add currently
            pass


        cmd.extend([
            '-y',
            '-loglevel', 'level+error',
            '-r', '{0:0.2f}'.format(self.framerate),
            *source,
            '-c:v', '{0:s}'.format(self.codec),
            '-b:v', '{0:s}'.format(self.bitrate),
            #'-filter:v', 'setpts=50*PTS',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
        ])


        extra_options = self.ffmpeg_extra_options.split(' ') if self.ffmpeg_extra_options else []
        if self.codec == 'libx264':
            extra_options = _x264_timelapse_options(self.bitrate, self.framerate, extra_options)
        if self.panorama:
            cmd.extend(panoramaVideoOptions(self.codec, self.video_filter, extra_options))
        else:
            if self.video_filter:
                logger.warning('Setting FFMPEG video filter: %s', self.video_filter)
                cmd.extend(['-vf', self.video_filter])
            elif self.vf_scale:
                logger.warning('Setting FFMPEG scaling option: %s', self.vf_scale)
                cmd.extend(['-vf', 'scale={0:s}'.format(self.vf_scale)])
            cmd.extend(extra_options)


        # With a custom frame-rate/filter graph the output frame count may differ
        # from the input count. Keep source progress, but do not guess an encode total.
        report_encoding = (self.activity is not None and frame_count > 0
                           and _preserves_frame_count(self.video_filter, extra_options))
        if report_encoding:
            cmd.extend(['-nostats', '-progress', 'pipe:1'])

        # finally add filename
        cmd.append('{0:s}'.format(str(video_file_p)))

        logger.info('FFmpeg command: %s', ' '.join(cmd))


        ffmpeg_env = dict()
        if self.config.get('TIMELAPSE', {}).get('FFMPEG_REPORT'):
            home_dir = Path(os.environ['HOME'])
            logger.warning('*** FFMPEG debug report will be generated in %s ***', home_dir)
            ffmpeg_env['FFREPORT'] = 'file={0:s}/ffmpeg-report-%t.log'.format(str(home_dir))


        try:
            output = self._encode(cmd, ffmpeg_env, stream, frame_count if report_encoding else None)
            elapsed_s = time.time() - start
            logger.info('Timelapse generated in %0.4f s', elapsed_s)

            for line in output.decode().split('\n'):
                logger.info('ffmpeg: %s', line)
        except (OSError, ValueError, TimelapseException):
            if stream is not None:
                video_file_p.unlink(missing_ok=True)
            raise
        except subprocess.CalledProcessError as e:
            elapsed_s = time.time() - start

            logger.info('FFMPEG ran for %0.4f s', elapsed_s)
            logger.error('FFMPEG failed to generate timelapse, return code: %d', e.returncode)

            for line in e.stdout.decode().split('\n'):
                logger.error('ffmpeg: %s', line)

            ### Check if video file was created
            if video_file_p.is_file():
                logger.error('FFMPEG created broken video file, cleaning up')
                video_file_p.unlink()

            raise TimelapseException('FFMPEG return code %d', e.returncode)


        # set default permissions
        video_file_p.chmod(0o644)



    def _encode(self, cmd, env, frames, total):
        # Keep diagnostics separate from FFmpeg's machine-readable progress.
        # When stdin carries aligned images, drain stdout while writing them.
        with tempfile.TemporaryFile() as log, subprocess.Popen(
                cmd, env=env, stdin=subprocess.PIPE if frames is not None else None,
                stdout=subprocess.PIPE if total else log, stderr=log,
                preexec_fn=lambda: os.nice(19)) as encoder:
            reader = None
            try:
                if total:
                    self.activity.progress('Encoding frames', 0, total)
                    if frames is None:
                        self._read_progress(encoder.stdout, total)
                    else:
                        reader = Thread(target=self._read_progress, args=(encoder.stdout, total))
                        reader.start()
                if frames is not None:
                    try:
                        with encoder.stdin:
                            for frame in frames:
                                encoder.stdin.write(frame)
                    except BrokenPipeError:
                        pass  # Report the encoder's exit status and diagnostics.
                code = encoder.wait()
            except BaseException:
                encoder.kill()
                encoder.wait()
                raise
            finally:
                if reader is not None:
                    reader.join()
                if total:
                    self.activity.finish_progress()
            log.seek(0)
            output = log.read()
            if code:
                raise subprocess.CalledProcessError(code, cmd, output=output)
            return output


    def _read_progress(self, stream, total):
        for line in stream:
            key, _, value = line.partition(b'=')
            if key == b'frame' and value.strip().isdigit():
                done = int(value)
                if 0 < done <= total:
                    self.activity.progress('Encoding frames', done, total)
