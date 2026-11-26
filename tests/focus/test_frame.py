from __future__ import annotations

import datetime

import cv2
import numpy as np
import pytest

from indi_allsky.focus import frame
from indi_allsky.focus.frame import HEADER
from indi_allsky.focus.frame import Stretch
from indi_allsky.focus.measure import to_gray
from tests.focus import synth


def test_decode_u16_stream():
    rng = np.random.default_rng(1)
    src = rng.integers(0, 65535, (6, 8), dtype=np.uint16)
    img, full = frame.decode_stream(src.astype('<u2').tobytes(), 8, 6, '')
    assert full == 65535.0
    assert img.dtype == np.uint16
    assert np.array_equal(img, src)


def test_decode_8bit_and_rgb24_streams():
    src = np.arange(48, dtype=np.uint8).reshape(6, 8)
    img, full = frame.decode_stream(src.tobytes(), 8, 6, '')
    assert full == 255.0
    assert np.array_equal(img, src)

    rgb = np.dstack([src, src, src])
    img, full = frame.decode_stream(rgb.tobytes(), 8, 6, '')
    assert full == 255.0
    assert img.shape == (6, 8)
    assert np.array_equal(img, src)


def test_decode_jpeg_stream():
    src = np.full((32, 48), 120, np.uint8)
    ok, enc = cv2.imencode('.jpg', src)
    assert ok
    img, full = frame.decode_stream(enc.tobytes(), 48, 32, 'image/jpeg')
    assert full == 255.0
    assert img.shape == (32, 48)
    assert abs(int(img.mean()) - 120) <= 2


def test_decode_wrong_length_returns_none():
    img, full = frame.decode_stream(b'\x00' * 13, 8, 6, '')
    assert img is None
    assert full is None


def test_decode_corrupt_jpeg_returns_none():
    img, full = frame.decode_stream(b'\xff\xd8garbage', 8, 6, '')
    assert img is None
    assert full is None


def test_maxpool_keeps_one_pixel_star_brightness():
    g = np.full((64, 64), 100, np.uint16)
    g[31, 17] = 1000
    # a plain 16-bit -> 8-bit scale would put 1000 at 3; stretched to [100, 1000] it must be 255
    out = frame.preview(g, Stretch(black=100.0, white=1000.0, gamma=1.0))
    assert out.shape == (32, 32)
    assert out.dtype == np.uint8
    assert out.max() == 255
    assert (out == 255).sum() == 1
    assert out[15, 8] == 255


def test_maxpool_drops_odd_trailing_row_and_column():
    g = np.zeros((5, 7), np.uint8)
    assert frame.preview(g, None).shape == (2, 3)


def test_preview_linear_scales_by_dtype_range():
    g16 = np.array([[0, 65535], [257, 257 * 100]], np.uint16)
    out = frame.preview(g16, None)
    assert out.shape == (1, 1)
    assert out[0, 0] == 255
    g8 = np.array([[10, 200], [30, 40]], np.uint8)
    assert frame.preview(g8, None)[0, 0] == 200


def test_stretch_from_frame_levels():
    rng = np.random.default_rng(2)
    g = rng.normal(1000, 20, (200, 200)).clip(0, 65535).astype(np.uint16)
    g[100, 100] = 60000
    s = Stretch.from_frame(g)
    assert s.gamma == 0.8
    assert abs(s.black - np.percentile(g, 5)) < 1e-6
    # the 99.995th percentile of 40000 px sits below the single hot pixel, so median + 60 sigma (~2200) wins
    assert 2000 < s.white < 2500
    out = frame.preview(g, s)
    assert out.max() == 255


CLIP = 0.98 * 65535.0


def test_auto_stretch_ignores_the_moon():
    # a clipped disc with a wide halo, and faint stars far from it
    moon = synth.Glint(150.0, 150.0, 15.0, 80000)
    halo = synth.Star(150.0, 150.0, 40.0, 1.0e7)
    stars = [synth.Star(420.3, 400.2, 1.0, 6000), synth.Star(420.3, 120.2, 1.0, 6000)]
    gray = to_gray(synth.frame(shape=(512, 512), stars=[halo, *stars], glints=[moon]), 'RGGB')
    sky = float(np.median(gray))

    everything = Stretch.from_frame(gray)
    auto = Stretch.from_frame(gray, clip=CLIP)

    assert everything.white >= CLIP * 0.9           # today: the moon sets white, and the sky is black
    assert sky < auto.white < sky + 0.1 * (everything.white - sky)
    assert auto.black == pytest.approx(everything.black, rel=0.05)


def test_auto_stretch_when_the_glare_fills_the_frame():
    gray = np.full((128, 128), 65535, np.uint16)
    gray[:, :8] = 3000                              # a sliver of sky, under the glare disc's reach

    s = Stretch.from_frame(gray, clip=CLIP)

    assert s.black < s.white <= CLIP


def test_auto_stretch_white_never_over_the_clip():
    rng = np.random.default_rng(3)
    gray = rng.normal(30000, 8000, (200, 200)).clip(0, 60000).astype(np.uint16)  # median + 60 sigma >> full scale

    s = Stretch.from_frame(gray, clip=CLIP)

    assert s.white == pytest.approx(CLIP)


def test_clock_is_small():
    h, w = 1600, 1600
    img = np.zeros((h, w), np.uint8)
    frame.draw_clock(img, 1700000000.123, 42)
    rows = np.where(img.any(axis=1))[0]
    cols = np.where(img.any(axis=0))[0]
    tall = h // frame.CLOCK_FRACTION
    assert rows.size
    assert rows.max() - rows.min() + 1 <= tall + 4
    assert rows.min() > h - 2 * tall - 4     # bottom
    assert cols.min() < 2 * tall             # left


def test_clock_draws_on_colour_image_in_place():
    img = np.full((300, 400, 3), 90, np.uint8)
    frame.draw_clock(img, 0.0, 1)
    assert img.max() == 255
    assert (img == 0).any()


def _offset(t):
    z = t.astimezone().strftime('%z')
    return z[:3] + ':' + z[3:]


def test_clock_text_is_local_time_like_the_overlay():
    local = datetime.datetime.fromtimestamp(1700000000.5)
    assert frame.clock_text(1700000000.5, '%Y.%m.%d %H:%M:%S') == local.strftime('%Y.%m.%d %H:%M:%S') + '.500'


def test_iso_clock_carries_the_utc_offset():
    local = datetime.datetime.fromtimestamp(1700000000.5)
    assert frame.clock_text(1700000000.5) == local.strftime('%Y-%m-%dT%H:%M:%S') + '.500' + _offset(local)


def test_milliseconds_go_before_an_offset_in_the_overlay_format():
    local = datetime.datetime.fromtimestamp(1700000000.5)
    z = local.astimezone().strftime('%z')
    assert frame.clock_text(1700000000.5, '%H:%M:%S%z') == local.strftime('%H:%M:%S') + '.500' + z
    assert frame.clock_text(1700000000.5, '%H:%M:%S %:z') == local.strftime('%H:%M:%S') + '.500 ' + _offset(local)


def test_clock_text_adds_milliseconds_only_after_seconds():
    local = datetime.datetime.fromtimestamp(1700000000.5)
    assert frame.clock_text(1700000000.5, '%d %b %H:%M') == local.strftime('%d %b %H:%M')


DEFAULT_TEMPLATE = '# size:30\n# xy:-15,15\n# color:150,0,0\n{timestamp:%Y.%m.%d %H:%M:%S}\nLat {latitude:+0.0f}'


@pytest.mark.parametrize('system, template, expected', [
    ('pillow', DEFAULT_TEMPLATE, '%Y.%m.%d %H:%M:%S'),          # the overlay's own format
    ('opencv', 'Time {timestamp:%H:%M}\nStars {stars:d}', '%H:%M'),
    ('off', DEFAULT_TEMPLATE, frame.ISO_CLOCK_FORMAT),          # labels off: nothing to match
    ('pillow', 'Stars {stars:d}', frame.ISO_CLOCK_FORMAT),      # no timestamp in the label
    ('pillow', '{timestamp}', frame.ISO_CLOCK_FORMAT),          # a timestamp with no format
    ('pillow', '# {timestamp:%H}\n{timestamp:%Y %H}', '%Y %H'),  # a setting line is not the label
    ('pillow', '', frame.ISO_CLOCK_FORMAT),
])
def test_clock_format_follows_the_overlay(system, template, expected):
    assert frame.clock_format(system, template) == expected


def test_clock_characters_sit_in_equal_cells():
    # monospace: a narrow '1' takes the same room as a wide '0', so the stamp does not jitter as the digits change
    a = np.full((800, 800), 90, np.uint8)
    b = np.full((800, 800), 90, np.uint8)
    frame.draw_clock(a, 1700000000.0, 11111)
    frame.draw_clock(b, 1700000000.0, 88888)
    right_a = np.where((a[:, 400:] == 0).any(axis=0))[0]
    right_b = np.where((b[:, 400:] == 0).any(axis=0))[0]
    assert right_a.size and right_a.min() == right_b.min()   # the frame number's box: as wide for 1s as for 8s


def test_frame_number_sits_in_the_bottom_right_corner_at_the_clock_size():
    img = np.full((800, 21200), 90, np.uint8)  # wide, so the boxes are far apart
    frame.draw_clock(img, 1700000000.0, 42)
    box = img == 0
    assert box[-1, 0] and box[-1, -1]                     # a box in each bottom corner
    assert not box[-1, 1200]                               # with picture between them
    left_rows = np.where(box[:, 0])[0]
    right_rows = np.where(box[:, -1])[0]
    assert left_rows.min() == right_rows.min()            # the same height: the same font size
    right = np.where(box[-1, 1200:])[0]
    assert (img[left_rows.min():, 1200 + right.min():] == 255).any()   # the number is drawn in it


def test_clock_stays_readable_on_a_small_region():
    img = np.zeros((120, 400), np.uint8)
    frame.draw_clock(img, 1700000000.0, 3)
    rows = np.where(img.any(axis=1))[0]
    assert rows.max() - rows.min() + 1 >= frame.CLOCK_MIN_HEIGHT


def test_encode_jpeg_is_valid_jpeg_gray_and_colour():
    for img in (np.full((40, 60), 128, np.uint8), np.full((40, 60, 3), 128, np.uint8)):
        data = frame.encode_jpeg(img)
        assert data[:2] == b'\xff\xd8'
        back = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        assert back.shape[:2] == (40, 60)


def test_encode_jpeg_simplejpeg_path(monkeypatch):
    calls = {}

    class Fake:
        @staticmethod
        def encode_jpeg(img, quality, colorspace):
            calls['args'] = (img.shape, quality, colorspace)
            return b'\xff\xd8fake'

    monkeypatch.setattr(frame, 'simplejpeg', Fake)
    assert frame.encode_jpeg(np.zeros((4, 6), np.uint8)) == b'\xff\xd8fake'
    assert calls['args'] == ((4, 6, 1), 85, 'GRAY')


def test_header_round_trip():
    assert HEADER.size == 29
    jpeg = b'\xff\xd8abc\xff\xd9'
    buf = frame.pack_frame(jpeg, 9, 1700000000.25, 0.5, 120.0, 77)
    assert buf[:4] == b'IAFF'
    assert buf[HEADER.size:] == jpeg
    hdr = frame.unpack_header(buf)
    assert hdr == {
        'magic': b'IAFF', 'version': 1, 'frame_no': 9, 'capture_time': 1700000000.25,
        'exposure': 0.5, 'gain': 120.0, 'cmd_id': 77,
    }


def test_unpack_header_rejects_bad_magic():
    buf = bytearray(frame.pack_frame(b'x', 1, 0.0, 1.0, 1.0, 0))
    buf[0:4] = b'NOPE'
    with pytest.raises(ValueError):
        frame.unpack_header(bytes(buf))


def test_unpack_header_rejects_bad_version_and_short_buffer():
    buf = bytearray(frame.pack_frame(b'x', 1, 0.0, 1.0, 1.0, 0))
    buf[4] = 2
    with pytest.raises(ValueError):
        frame.unpack_header(bytes(buf))
    with pytest.raises(ValueError):
        frame.unpack_header(b'IAFF\x01')
