import shutil
import subprocess

import numpy
import pytest

from indi_allsky.panorama import buildPanoramaCropFilter
from indi_allsky.panorama import buildPanoramaPanFilter
from indi_allsky.panorama import buildPanoramaTimedPanFilter
from indi_allsky.panorama import cropPanoramaArray
from indi_allsky.panorama import panoramaSourceCircleClipped
from indi_allsky.panorama import validatePanoramaAspectRatio
from indi_allsky.panorama import validatePanoramaMiniTimelapseRequest


FFMPEG_PATH = shutil.which('ffmpeg')


def _run_ffmpeg_filter(source, filter_graph, output_shape, framerate=25):
    source_height, source_width = source.shape[-2:]
    frame_count = source.shape[0] if source.ndim == 3 else 1
    command = (
        FFMPEG_PATH,
        '-v', 'error',
        '-r', str(framerate),
        '-f', 'rawvideo',
        '-pixel_format', 'gray',
        '-video_size', '{0:d}x{1:d}'.format(source_width, source_height),
        '-i', 'pipe:0',
        '-vf', filter_graph,
        '-frames:v', str(frame_count),
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


def test_linear_pan_without_seam_uses_dynamic_crop():
    assert buildPanoramaPanFilter(
        4096, 1024,
        200, 100,
        800, 300,
        1000, 600,
        11,
    ) == (
        'crop=w=1000:h=600:'
        'x=trunc((200+600*n/10)/2)*2:'
        'y=trunc((100+200*n/10)/2)*2'
    )


@pytest.mark.parametrize(
    'direction,delta_x',
    (
        ('left_to_right', '+696'),
        ('right_to_left', '-3400'),
    ),
)
def test_linear_pan_wraps_across_seam(direction, delta_x):
    assert buildPanoramaPanFilter(
        4096, 1024,
        3600, 100,
        200, 100,
        1000, 600,
        11,
        direction=direction,
    ) == (
        'split=2[pano_0][pano_1];'
        '[pano_0][pano_1]hstack=inputs=2[pano_strip];'
        '[pano_strip]crop=w=1000:h=600:'
        r'x=trunc(mod((3600{0:s}*n/10)+4096\,4096)/2)*2:'
        'y=trunc((100+0*n/10)/2)*2'
    ).format(delta_x)


@pytest.mark.parametrize(
    'direction,start_x,end_x,delta_x',
    (
        ('full_left_to_right', 200, 200, '+4096'),
        ('full_right_to_left', 200, 200, '-4096'),
        ('full_left_to_right', 3600, 200, '+4792'),
        ('full_right_to_left', 3600, 200, '-7496'),
    ),
)
def test_linear_pan_full_turn_routes(direction, start_x, end_x, delta_x):
    filter_graph = buildPanoramaPanFilter(
        4096, 1024,
        start_x, 100,
        end_x, 100,
        1000, 600,
        11,
        direction=direction,
    )
    expected_filter = (
        'split=2[pano_0][pano_1];'
        '[pano_0][pano_1]hstack=inputs=2[pano_strip];'
        '[pano_strip]crop=w=1000:h=600:'
        r'x=trunc(mod(({0:d}{1:s}*n/10)+4096\,4096)/2)*2:'
        'y=trunc((100+0*n/10)/2)*2'
    ).format(start_x, delta_x)

    assert filter_graph == expected_filter


@pytest.mark.parametrize('direction', ('left_to_right', 'right_to_left'))
def test_directed_pan_to_same_crop_does_not_make_full_turn(direction):
    assert buildPanoramaPanFilter(
        4096, 1024,
        200, 100,
        200, 100,
        1000, 600,
        11,
        direction=direction,
    ) == 'crop=w=1000:h=600:x=200:y=100'


def test_linear_pan_rejects_too_few_frames():
    with pytest.raises(ValueError, match='at least two frames'):
        buildPanoramaPanFilter(4096, 1024, 0, 0, 200, 0, 1000, 600, 1)


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
        'crop_x'       : 3600,
        'crop_y'       : 100,
        'crop_width'   : 1000,
        'crop_height'  : 600,
        'aspect_ratio' : 'free',
        'pan_mode'     : 'static',
        'end_crop_x'   : 3600,
        'end_crop_y'   : 100,
        'pan_direction' : 'shortest',
    }


def test_panorama_route_validation_normalizes_linear_pan():
    selection = validatePanoramaMiniTimelapseRequest(
        4096,
        1024,
        {
            'CROP_X'       : '3600',
            'CROP_Y'       : '100',
            'CROP_WIDTH'   : '1000',
            'CROP_HEIGHT'  : '600',
            'ASPECT_RATIO' : 'free',
            'PAN_MODE'     : 'linear',
            'END_CROP_X'   : '200',
            'END_CROP_Y'   : '300',
            'PAN_DIRECTION': 'full_left_to_right',
        },
    )

    assert selection['pan_mode'] == 'linear'
    assert selection['end_crop_x'] == 200
    assert selection['end_crop_y'] == 300
    assert selection['pan_direction'] == 'full_left_to_right'


@pytest.mark.parametrize(
    'changes',
    (
        {'CROP_HEIGHT': None},
        {'CROP_X': 'left'},
        {'CROP_HEIGHT': 1082},
        {'ASPECT_RATIO': '2.39:1'},
        {'PAN_MODE': 'linear', 'END_CROP_X': 0},
        {
            'PAN_MODE': 'linear',
            'END_CROP_X': 2,
            'END_CROP_Y': 0,
            'PAN_DIRECTION': 'around_twice',
        },
    ),
)
def test_panorama_route_validation_rejects_bad_selection(changes):
    selection = {
        'CROP_X'       : 0,
        'CROP_Y'       : 0,
        'CROP_WIDTH'   : 1920,
        'CROP_HEIGHT'  : 1080,
        'ASPECT_RATIO' : '16:9',
    }
    selection.update(changes)
    selection = {key: value for key, value in selection.items() if value is not None}

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


@pytest.mark.skipif(FFMPEG_PATH is None, reason='FFmpeg is not installed')
def test_ffmpeg_filter_graph_moves_crop_across_panorama_seam():
    source_frame = numpy.tile(numpy.arange(8, dtype=numpy.uint8), (4, 1))
    source = numpy.repeat(source_frame[numpy.newaxis, :, :], 3, axis=0)
    filter_graph = buildPanoramaPanFilter(
        8, 4,
        6, 0,
        2, 0,
        4, 2,
        3,
        direction='left_to_right',
    )
    expected = numpy.stack([
        cropPanoramaArray(source_frame, crop_x, 0, 4, 2)
        for crop_x in (6, 0, 2)
    ])
    actual = _run_ffmpeg_filter(source, filter_graph, expected.shape)

    numpy.testing.assert_array_equal(actual, expected)


@pytest.mark.skipif(FFMPEG_PATH is None, reason='FFmpeg is not installed')
def test_ffmpeg_filter_graph_makes_full_turn_to_same_crop():
    source_frame = numpy.tile(numpy.arange(8, dtype=numpy.uint8), (4, 1))
    source = numpy.repeat(source_frame[numpy.newaxis, :, :], 5, axis=0)
    filter_graph = buildPanoramaPanFilter(
        8, 4,
        2, 0,
        2, 0,
        4, 2,
        5,
        direction='full_left_to_right',
    )
    expected = numpy.stack([
        cropPanoramaArray(source_frame, crop_x, 0, 4, 2)
        for crop_x in (2, 4, 6, 0, 2)
    ])
    actual = _run_ffmpeg_filter(source, filter_graph, expected.shape)

    numpy.testing.assert_array_equal(actual, expected)


@pytest.mark.skipif(FFMPEG_PATH is None, reason='FFmpeg is not installed')
def test_ffmpeg_filter_graph_honors_two_frame_endpoints():
    source_frame = numpy.tile(numpy.arange(8, dtype=numpy.uint8), (4, 1))
    source = numpy.repeat(source_frame[numpy.newaxis, :, :], 2, axis=0)
    filter_graph = buildPanoramaPanFilter(
        8, 4,
        6, 0,
        2, 2,
        4, 2,
        2,
        direction='left_to_right',
    )
    expected = numpy.stack([
        cropPanoramaArray(source_frame, 6, 0, 4, 2),
        cropPanoramaArray(source_frame, 2, 2, 4, 2),
    ])
    actual = _run_ffmpeg_filter(source, filter_graph, expected.shape)

    numpy.testing.assert_array_equal(actual, expected)


@pytest.mark.skipif(FFMPEG_PATH is None, reason='FFmpeg is not installed')
@pytest.mark.parametrize('framerate', (0.25, 0.5, 0.75, 1, 2, 5, 10, 25, 30, 60))
def test_timed_pan_preserves_capture_progress_across_gap(tmp_path, framerate):
    source_frame = numpy.tile(numpy.arange(8, dtype=numpy.uint8), (4, 1))
    source = numpy.repeat(source_frame[numpy.newaxis, :, :], 4, axis=0)
    command_file = tmp_path.joinpath('panorama_pan.txt')
    filter_graph = buildPanoramaTimedPanFilter(
        8, 4,
        0, 0,
        0, 2,
        4, 2,
        (0, 15, 45, 60),
        framerate,
        command_file,
        direction='full_left_to_right',
    )
    expected = numpy.stack([
        cropPanoramaArray(source_frame, crop_x, crop_y, 4, 2)
        for crop_x, crop_y in ((0, 0), (2, 0), (6, 0), (0, 2))
    ])
    actual = _run_ffmpeg_filter(source, filter_graph, expected.shape, framerate=framerate)

    numpy.testing.assert_array_equal(actual, expected)
