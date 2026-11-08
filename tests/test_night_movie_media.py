from datetime import date
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

from indi_allsky.exceptions import TimelapseException
from indi_allsky.night_movie import local_sources, playable, prior_attempt, readable_images, staged_movie


class NightMovieMediaTests(unittest.TestCase):
    def test_source_filter_and_signature_track_returned_files(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory, 'frame.jpg')
            bad = Path(directory, 'bad.jpg')
            bad.write_bytes(b'broken')
            entries = [SimpleNamespace(id=n, getFilesystemPath=lambda p=p: p) for n, p in enumerate((frame, bad))]
            missing, _ = local_sources(entries, 0)
            Image.new('RGB', (4, 4)).save(frame)
            returned, paths = local_sources(entries, 0)
            self.assertNotEqual(missing, returned)
            self.assertEqual(list(readable_images(paths)), [frame])
            self.assertEqual(local_sources(entries, 0)[0], returned)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is required')
    def test_real_encoded_video_is_required_before_atomic_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            movie = Path(directory, 'night.mp4')
            args = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=16x16',
                    '-frames:v', '2', '-c:v', 'libx264', '-threads', '1']
            with staged_movie(movie) as stage:
                subprocess.run([*args, str(stage)], check=True)
                self.assertFalse(movie.exists())
            original = movie.read_bytes()
            self.assertTrue(playable(movie))
            with self.assertRaises(TimelapseException):
                with staged_movie(movie) as stage:
                    stage.write_bytes(b'invalid replacement attempt')
            self.assertEqual(movie.read_bytes(), original)
            self.assertEqual(list(movie.parent.iterdir()), [movie])

    def test_attempt_slots_do_not_suppress_a_later_night(self):
        slot = SimpleNamespace(value='{"day":"2026-11-01","deleted":true}')
        self.assertEqual(prior_attempt(slot, date(2026, 11, 5)), {})
        self.assertTrue(prior_attempt(slot, date(2026, 11, 1))['deleted'])


def test_encoder_config_changes_unlock_a_new_repair_attempt():
    from indi_allsky.night_movie import movie_inputs
    cfg = {'FFMPEG_CODEC': 'libx264', 'IMAGE_FILE_TYPE': 'jpg'}
    before = movie_inputs('sources', cfg)
    assert movie_inputs('sources', dict(cfg, unrelated=42)) == before
    assert movie_inputs('sources', dict(cfg, FFMPEG_CODEC='libx265')) != before


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg and ffprobe are required')
class PanoramaPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.movie = Path(self.directory.name, 'panorama.mp4')

    def encode(self, size='160x32', frames=30, options=()):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size={}:rate=5'.format(size), '-frames:v', str(frames),
                        '-c:v', 'libx264', '-g', '3', '-threads', '1', '-movflags', '+faststart',
                        *options, str(self.movie)], check=True)

    def test_short_panorama_and_static_sky_are_valid(self):
        from indi_allsky.night_movie import panorama_playable
        self.encode(frames=2, options=('-vf', 'drawbox=color=black:t=fill'))
        self.assertTrue(panorama_playable(self.movie))
        self.encode(frames=1)
        self.assertTrue(panorama_playable(self.movie))

    def test_wide_panorama_and_incorrect_h264_level_do_not_pass(self):
        from indi_allsky.night_movie import panorama_playable
        self.encode(size='2048x96', frames=2)
        self.assertTrue(playable(self.movie))
        self.assertFalse(panorama_playable(self.movie))
        self.encode(size='320x240', frames=2, options=('-level:v', '1.0'))
        self.assertFalse(panorama_playable(self.movie))
        self.encode(size='1920x32', frames=2, options=('-level:v', '2.0'))
        self.assertFalse(panorama_playable(self.movie))

    def test_playable_beginning_does_not_hide_missing_tail(self):
        import json
        from indi_allsky.night_movie import panorama_playable
        self.encode()
        packets = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
            'packet=pos,size', '-of', 'json', str(self.movie)]))['packets']
        last = packets[8]
        with self.movie.open('r+b') as stream:
            stream.truncate(int(last['pos']) + int(last['size']))
        self.assertTrue(playable(self.movie))
        self.assertFalse(panorama_playable(self.movie))

    def test_staged_panorama_must_decode_one_frame_per_source(self):
        self.encode(frames=2)
        original = self.movie.read_bytes()
        with self.assertRaises(TimelapseException):
            with staged_movie(self.movie, panorama_frames=3) as staged:
                staged.write_bytes(original)
        self.assertEqual(self.movie.read_bytes(), original)
        with staged_movie(self.movie, panorama_frames=2) as staged:
            staged.write_bytes(original)

    def test_webm_can_be_validated_without_a_container_frame_count(self):
        from indi_allsky.night_movie import panorama_frames, panorama_playable
        encoders = subprocess.check_output(['ffmpeg', '-hide_banner', '-encoders'], text=True)
        if ' libvpx ' not in encoders:
            self.skipTest('VP8 encoder is not installed')
        webm = self.movie.with_suffix('.webm')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=160x32:r=5',
                        '-frames:v', '3', '-c:v', 'libvpx', '-threads', '1', str(webm)], check=True)
        self.assertEqual(panorama_frames(webm), 3)
        self.assertTrue(panorama_playable(webm, expected_frames=3))
        self.assertFalse(panorama_playable(webm, expected_frames=4))
