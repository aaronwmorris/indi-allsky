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
