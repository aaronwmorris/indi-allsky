from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from indi_allsky.aligned_media import SkyRemap, process_stack_frame, stack_entries
from indi_allsky.exceptions import KeogramMismatchException


def frame(roll):
    return SimpleNamespace(width=128, height=128, binmode=1, adu=27, stars=81, data={
        'star_alignment': {
            'id': 'setup-' + str(roll),
            'image_size': [128, 128],
            'values': {'AZIMUTH_ANGLE': roll, 'IMAGE_CIRCLE_DIAMETER': 128,
                       'OFFSET_X': 0, 'OFFSET_Y': 0, 'RADIAL_DISTORTION': 0,
                       'LENS_ALTITUDE': 90, 'POINTING_AZIMUTH': 0},
        }
    })


def test_archived_stack_uses_one_coordinate_system_and_ignores_pending_frames():
    from sqlalchemy import JSON, Column, Integer, create_engine
    from sqlalchemy.orm import Session, declarative_base

    base = declarative_base()

    class Image(base):
        __tablename__ = 'image'
        id = Column(Integer, primary_key=True)
        width = Column(Integer, default=128)
        height = Column(Integer, default=128)
        data = Column(JSON)

    engine = create_engine('sqlite://')
    base.metadata.create_all(engine)
    with Session(engine) as db:
        manual = Image(data={})
        pending = Image(data={'star_alignment': None})
        wrong_size = Image(data=frame(180).data, width=64)
        db.add_all([manual, pending, wrong_size])
        db.flush()
        all_images = db.query(Image).order_by(Image.id)
        selected, count = stack_entries(all_images, Image)
        assert count == 1 and list(selected) == [manual]
        selected, count = stack_entries(all_images.filter(Image.id != manual.id), Image)
        assert count == 0 and not list(selected)

        registered = Image(data=frame(90).data)
        other_setup = Image(data=frame(0).data)
        db.add_all([registered, other_setup, Image(data={})])
        db.flush()
        selected, count = stack_entries(all_images, Image)
        assert count == 2 and list(selected) == [registered, other_setup]


def test_keogram_and_star_trails_align_after_sensor_space_filtering(tmp_path):
    path = tmp_path / 'frame.jpg'
    path.touch()
    raw = np.zeros((128, 128, 3), dtype=np.uint8)
    # For this camera roll, geographic north is to the right in the raw image.
    raw[64, 96] = (1, 2, 3)
    kg, trails = Mock(), Mock()
    process_stack_frame(frame(90), path, raw, SkyRemap(), kg, trails, True)
    np.testing.assert_array_equal(kg.processImage.call_args.args[0][32, 64], (1, 2, 3))
    assert kg.x_offset == kg.y_offset == 0
    args, kwargs = trails.processImage.call_args
    assert args[1] is raw
    assert (kwargs['adu'], kwargs['star_count']) == (27, 81)
    np.testing.assert_array_equal(kwargs['align'](raw)[32, 64], (1, 2, 3))

    # A manually oriented image and its native offsets remain usable, including
    # when the keogram rejects the image dimensions but trails can still use it.
    manual = frame(0)
    manual.data = {}
    kg.x_offset = 14
    kg.processImage.side_effect = KeogramMismatchException()
    process_stack_frame(manual, path, raw, SkyRemap(), kg, trails, False)
    assert kg.processImage.call_args.args[0] is raw
    assert kg.x_offset == 14
    assert trails.processImage.call_args.kwargs == {'adu': None, 'star_count': None, 'align': None}


@pytest.mark.parametrize('aligned', [False, True])
def test_star_trails_can_be_rebuilt_without_a_keogram(tmp_path, aligned):
    entry = frame(90)
    if not aligned:
        entry.data = {}
    path = tmp_path / 'frame.jpg'
    path.touch()
    raw = np.zeros((128, 128, 3), dtype=np.uint8)
    raw[64, 96] = (1, 2, 3)
    trails = Mock()

    process_stack_frame(entry, path, raw, SkyRemap(), None, trails, True)

    args, kwargs = trails.processImage.call_args
    assert args[1] is raw
    if aligned:
        np.testing.assert_array_equal(kwargs['align'](raw)[32, 64], (1, 2, 3))
    else:
        assert kwargs['align'] is None
