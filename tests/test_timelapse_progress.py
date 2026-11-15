"""Count the frames FFmpeg actually encodes in file and aligned-pipe mode."""
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from indi_allsky.exceptions import TimelapseException
from indi_allsky.timelapse import TimelapseGenerator, _preserves_frame_count


pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg required')


class RecordingActivity:
    def __init__(self):
        self.samples = []
        self.current_stage = None

    def progress(self, stage, completed, total):
        self.current_stage = stage
        self.samples.append((stage, completed, total))

    def finish_progress(self):
        self.current_stage = None

    def track(self, stage, items, total):
        self.progress(stage, 0, total)
        for n, item in enumerate(items, 1):
            yield item
            self.progress(stage, n, total)
        self.finish_progress()


def fixture_movie(directory, stream):
    paths = []
    for n in range(4):
        path = directory / f'{n}.png'
        assert cv2.imwrite(str(path), np.full((32, 32, 3), n * 25, dtype=np.uint8))
        paths.append(path)
    activity = RecordingActivity()
    gen = TimelapseGenerator({'IMAGE_FILE_TYPE': 'png'}, skip_frames=1, activity=activity)
    gen.ffmpeg_bin = shutil.which('ffmpeg')
    if stream:
        # Mixed archives may contain already registered images, sent unchanged.
        gen.pre_processor.frame_alignments = {directory / 'outside-selection.png': {}}
        if not hasattr(gen.pre_processor, 'encoded_frames'):
            gen.pre_processor.encoded_frames = lambda frames, suffix: (path.read_bytes() for path in frames)
    return gen, activity, paths


@pytest.mark.parametrize('stream', [False, True])
def test_reports_encoded_frames_after_skips_and_keeps_movie_intact(tmp_path, stream):
    gen, activity, paths = fixture_movie(tmp_path, stream)
    target = tmp_path / 'movie.mp4'
    gen.generate(target, paths, preserve_order=True)
    counts = [n for stage, n, total in activity.samples if stage == 'Encoding frames' and total == 3]
    assert counts[0] == 0 and counts[-1] == 3
    assert counts == sorted(counts)
    assert activity.current_stage is None
    decoded = subprocess.check_output([gen.ffmpeg_bin, '-v', 'error', '-i', str(target),
        '-vf', 'scale=1:1', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'])
    assert len(decoded) == 3


def test_encoder_failure_clears_live_count(tmp_path):
    gen, activity, paths = fixture_movie(tmp_path, False)
    gen.codec = 'missing_encoder_for_this_test'
    target = tmp_path / 'broken.mp4'
    with pytest.raises(TimelapseException):
        gen.generate(target, paths)
    assert ('Encoding frames', 0, 3) in activity.samples
    assert ('Encoding frames', 3, 3) not in activity.samples
    assert activity.current_stage is None and not target.exists()

@pytest.mark.parametrize(('graph', 'options', 'known'), [
    ('fps=1', [], False), ('crop=30:30,select=1', [], False), ('tpad=stop_duration=1', [], False),
    ('scale=20:20', ['-vf', 'crop=16:16'], True), ('crop=16:16', ['-filter:v:0', 'fps=2'], False),
    ('', ['-r', '10'], False), ('', ['-lavfi', 'fps=1'], False), ('', ['-level', '3.1'], True),
    ("sendcmd=f='/tmp/pan',split=2[a][b];[a][b]hstack=2,crop@pan=w=30:h=20", [], True),
])
def test_only_reports_encoder_totals_for_known_frame_preserving_filters(graph, options, known):
    assert _preserves_frame_count(graph, options) is known
