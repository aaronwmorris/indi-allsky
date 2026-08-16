import shutil
import subprocess

import numpy
import pytest

from indi_allsky.panorama import buildPanoramaCropFilter
from indi_allsky.panorama import cropPanoramaArray
from indi_allsky.panorama import panoramaSourceCircleClipped
from indi_allsky.panorama import validatePanoramaAspectRatio
from indi_allsky.panorama import validatePanoramaMiniTimelapseRequest


FFMPEG_PATH = shutil.which('ffmpeg')


def _run_ffmpeg_filter(source, filter_graph, output_shape):
    source_height, source_width = source.shape[:2]
    command = (
        FFMPEG_PATH,
        '-v', 'error',
        '-f', 'rawvideo',
        '-pixel_format', 'gray',
        '-video_size', '{0:d}x{1:d}'.format(source_width, source_height),
        '-i', 'pipe:0',
        '-vf', filter_graph,
        '-frames:v', '1',
        '-f', 'rawvideo',
        '-pix_fmt', 'gray',
        'pipe:1',
    )
    result = subprocess.run(
        command,
        input=source.tobytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    return numpy.frombuffer(result.stdout, dtype=numpy.uint8).reshape(output_shape)


def test_full_panorama_needs_no_filter():
    assert buildPanoramaCropFilter(4096, 1024, 0, 0, 4096, 1024) == ''


def test_crop_inside_saved_panorama_edges():
    assert buildPanoramaCropFilter(4096, 1024, 200, 100, 1200, 600) == (
        'crop=w=1200:h=600:x=200:y=100'
    )


def test_crop_wraps_saved_panorama_edge():
    assert buildPanoramaCropFilter(4096, 1024, 3600, 100, 1000, 600) == (
        'split=2[pano_right_src][pano_left_src];'
        '[pano_right_src]crop=w=496:h=600:x=3600:y=100[pano_right];'
        '[pano_left_src]crop=w=504:h=600:x=0:y=100[pano_left];'
        '[pano_right][pano_left]hstack=inputs=2'
    )


def test_full_width_crop_can_move_the_output_seam():
    assert buildPanoramaCropFilter(4096, 1024, 200, 0, 4096, 1024) == (
        'split=2[pano_right_src][pano_left_src];'
        '[pano_right_src]crop=w=3896:h=1024:x=200:y=0[pano_right];'
        '[pano_left_src]crop=w=200:h=1024:x=0:y=0[pano_left];'
        '[pano_right][pano_left]hstack=inputs=2'
    )


@pytest.mark.parametrize(
    'crop,error_text',
    (
        ((-2, 0, 100, 100), 'X coordinate'),
        ((4096, 0, 100, 100), 'X coordinate'),
        ((0, -2, 100, 100), 'Y coordinate'),
        ((0, 0, 4098, 100), 'width'),
        ((0, 900, 100, 200), 'height'),
        ((1, 0, 100, 100), 'must be even'),
        ((0, 0, 101, 100), 'must be even'),
    ),
)
def test_invalid_crop_is_rejected(crop, error_text):
    with pytest.raises(ValueError, match=error_text):
        buildPanoramaCropFilter(4096, 1024, *crop)


def test_odd_source_dimensions_are_rejected_for_yuv420_video():
    with pytest.raises(ValueError, match='must be even'):
        buildPanoramaCropFilter(4095, 1024, 0, 0, 1000, 600)


@pytest.mark.parametrize(
    'aspect_ratio,width,height',
    (
        ('free', 1000, 600),
        ('16:9', 1920, 1080),
        ('9:16', 1080, 1920),
        ('1:1', 1080, 1080),
        ('4:5', 1080, 1350),
        ('4:3', 1600, 1200),
        ('3:4', 1200, 1600),
        ('18:9', 2000, 1000),
        ('9:18', 1000, 2000),
        ('19.5:9', 1170, 540),
        ('9:19.5', 540, 1170),
        ('20:9', 1200, 540),
        ('9:20', 540, 1200),
        ('21:9', 1260, 540),
        ('9:21', 540, 1260),
    ),
)
def test_supported_aspect_ratios(aspect_ratio, width, height):
    assert validatePanoramaAspectRatio(aspect_ratio, width, height) == aspect_ratio


def test_fixed_aspect_ratio_rejects_mismatched_dimensions():
    with pytest.raises(ValueError, match='do not match'):
        validatePanoramaAspectRatio('16:9', 1920, 1082)


def test_unknown_aspect_ratio_is_rejected():
    with pytest.raises(ValueError, match='Unsupported'):
        validatePanoramaAspectRatio('2.39:1', 1920, 804)


def test_thumbnail_crop_inside_saved_panorama_edges():
    panorama = numpy.arange(4 * 8).reshape((4, 8))

    cropped = cropPanoramaArray(panorama, 2, 0, 4, 2)

    numpy.testing.assert_array_equal(cropped, panorama[0:2, 2:6])


def test_thumbnail_crop_wraps_saved_panorama_edge():
    panorama = numpy.arange(4 * 8).reshape((4, 8))

    cropped = cropPanoramaArray(panorama, 6, 0, 4, 2)

    expected = numpy.concatenate((panorama[0:2, 6:8], panorama[0:2, 0:2]), axis=1)
    numpy.testing.assert_array_equal(cropped, expected)


def test_thumbnail_crop_can_move_full_width_seam():
    panorama = numpy.arange(4 * 8).reshape((4, 8))

    cropped = cropPanoramaArray(panorama, 2, 0, 8, 4)

    expected = numpy.concatenate((panorama[:, 2:8], panorama[:, 0:2]), axis=1)
    numpy.testing.assert_array_equal(cropped, expected)


def test_panorama_source_circle_that_fits_is_not_clipped():
    assert panoramaSourceCircleClipped(400, 300, 300) is False


@pytest.mark.parametrize(
    'source_width,source_height,diameter,offset_x,offset_y',
    (
        (400, 300, 302, 0, 0),
        (400, 300, 300, 0, 2),
        (400, 300, 360, 30, 0),
    ),
)
def test_panorama_source_circle_clipping_is_detected(
    source_width,
    source_height,
    diameter,
    offset_x,
    offset_y,
):
    assert panoramaSourceCircleClipped(
        source_width,
        source_height,
        diameter,
        offset_x,
        offset_y,
    ) is True


def test_panorama_route_validation_normalizes_selection():
    selection = validatePanoramaMiniTimelapseRequest(
        4096,
        1024,
        {
            'CROP_X'      : '3600',
            'CROP_Y'      : '100',
            'CROP_WIDTH'  : '1000',
            'CROP_HEIGHT' : '600',
            'ASPECT_RATIO': 'free',
        },
    )

    assert selection == {
        'crop_x'      : 3600,
        'crop_y'      : 100,
        'crop_width'  : 1000,
        'crop_height' : 600,
        'aspect_ratio': 'free',
    }


@pytest.mark.parametrize(
    'selection',
    (
        {
            'CROP_X'      : 0,
            'CROP_Y'      : 0,
            'CROP_WIDTH'  : 1920,
            'ASPECT_RATIO': '16:9',
        },
        {
            'CROP_X'      : 'left',
            'CROP_Y'      : 0,
            'CROP_WIDTH'  : 1920,
            'CROP_HEIGHT' : 1080,
            'ASPECT_RATIO': '16:9',
        },
        {
            'CROP_X'      : 0,
            'CROP_Y'      : 0,
            'CROP_WIDTH'  : 1920,
            'CROP_HEIGHT' : 1082,
            'ASPECT_RATIO': '16:9',
        },
        {
            'CROP_X'      : 0,
            'CROP_Y'      : 0,
            'CROP_WIDTH'  : 1920,
            'CROP_HEIGHT' : 1080,
            'ASPECT_RATIO': '2.39:1',
        },
    ),
)
def test_panorama_route_validation_rejects_bad_selection(selection):
    with pytest.raises(ValueError):
        validatePanoramaMiniTimelapseRequest(4096, 2160, selection)


@pytest.mark.skipif(FFMPEG_PATH is None, reason='FFmpeg is not installed')
@pytest.mark.parametrize(
    'crop',
    (
        (2, 2, 4, 2),
        (6, 0, 4, 2),
        (2, 0, 8, 4),
    ),
)
def test_ffmpeg_filter_graph_matches_panorama_crop(crop):
    source = numpy.arange(4 * 8, dtype=numpy.uint8).reshape((4, 8))
    filter_graph = buildPanoramaCropFilter(8, 4, *crop)
    expected = cropPanoramaArray(source, *crop)
    actual = _run_ffmpeg_filter(source, filter_graph, expected.shape)

    numpy.testing.assert_array_equal(actual, expected)
