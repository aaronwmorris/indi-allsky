import math
from pathlib import Path

import numpy


PANORAMA_ASPECT_RATIOS = {
    'free' : None,
    '16:9' : (16, 9),
    '9:16' : (9, 16),
    '1:1'  : (1, 1),
    '4:5'  : (4, 5),
    '4:3'  : (4, 3),
    '3:4'  : (3, 4),
    '18:9' : (2, 1),
    '9:18' : (1, 2),
    '19.5:9' : (13, 6),
    '9:19.5' : (6, 13),
    '20:9' : (20, 9),
    '9:20' : (9, 20),
    '21:9' : (7, 3),
    '9:21' : (3, 7),
}

PANORAMA_PAN_MODES = ('static', 'linear')
PANORAMA_PAN_DIRECTIONS = (
    'shortest',
    'left_to_right',
    'right_to_left',
    'full_left_to_right',
    'full_right_to_left',
)


def panoramaSourceCircleClipped(
    source_width,
    source_height,
    circle_diameter,
    offset_x=0,
    offset_y=0,
):
    """Return whether the configured fisheye circle extends past the source image."""
    source_width, source_height, circle_diameter, offset_x, offset_y = map(
        int, (source_width, source_height, circle_diameter, offset_x, offset_y),
    )

    if source_width < 1 or source_height < 1 or circle_diameter < 1:
        raise ValueError('Panorama source and circle dimensions must be positive')

    available_width = source_width - (2 * abs(offset_x))
    available_height = source_height - (2 * abs(offset_y))

    return circle_diameter > min(available_width, available_height)


def validatePanoramaAspectRatio(aspect_ratio, crop_width, crop_height):
    aspect_ratio = str(aspect_ratio)

    try:
        ratio = PANORAMA_ASPECT_RATIOS[aspect_ratio]
    except KeyError:
        raise ValueError('Unsupported panorama aspect ratio')

    if ratio:
        ratio_width, ratio_height = ratio
        if int(crop_width) * ratio_height != int(crop_height) * ratio_width:
            raise ValueError('Panorama crop dimensions do not match the selected aspect ratio')

    return aspect_ratio


def buildPanoramaCropFilter(
    source_width,
    source_height,
    crop_x,
    crop_y,
    crop_width,
    crop_height,
):
    """Build an FFmpeg crop filter, wrapping only across the horizontal seam."""
    source_width, source_height, crop_x, crop_y, crop_width, crop_height = map(
        int, (source_width, source_height, crop_x, crop_y, crop_width, crop_height),
    )

    if source_width < 2 or source_height < 2:
        raise ValueError('Panorama source dimensions must be at least 2 x 2 pixels')

    if any(v % 2 for v in (source_width, source_height, crop_x, crop_y, crop_width, crop_height)):
        raise ValueError('Panorama source and crop coordinates and dimensions must be even')

    if crop_x < 0 or crop_x >= source_width:
        raise ValueError('Panorama crop X coordinate is outside the source image')

    if crop_y < 0 or crop_y >= source_height:
        raise ValueError('Panorama crop Y coordinate is outside the source image')

    if crop_width < 2 or crop_width > source_width:
        raise ValueError('Panorama crop width is outside the source image')

    if crop_height < 2 or crop_y + crop_height > source_height:
        raise ValueError('Panorama crop height is outside the source image')

    if (
        crop_x == 0
        and crop_y == 0
        and crop_width == source_width
        and crop_height == source_height
    ):
        return ''

    crop_end_x = crop_x + crop_width
    if crop_end_x <= source_width:
        return 'crop=w={0:d}:h={1:d}:x={2:d}:y={3:d}'.format(
            crop_width,
            crop_height,
            crop_x,
            crop_y,
        )

    right_width = source_width - crop_x
    left_width = crop_width - right_width

    return (
        'split=2[pano_right_src][pano_left_src];'
        '[pano_right_src]crop=w={right_width:d}:h={height:d}:x={x:d}:y={y:d}[pano_right];'
        '[pano_left_src]crop=w={left_width:d}:h={height:d}:x=0:y={y:d}[pano_left];'
        '[pano_right][pano_left]hstack=inputs=2'
    ).format(
        right_width=right_width,
        left_width=left_width,
        height=crop_height,
        x=crop_x,
        y=crop_y,
    )


def _panoramaPanDeltaX(source_width, start_x, end_x, direction):
    direct_delta_x = end_x - start_x
    if direction == 'shortest':
        if direct_delta_x > source_width / 2:
            return direct_delta_x - source_width
        if direct_delta_x < -(source_width / 2):
            return direct_delta_x + source_width
        return direct_delta_x
    if 'left_to_right' in direction:
        return (direct_delta_x % source_width) + (
            source_width if direction.startswith('full_') else 0
        )
    return -((-direct_delta_x) % source_width) - (
        source_width if direction.startswith('full_') else 0
    )


def buildPanoramaPanFilter(
    source_width,
    source_height,
    start_x,
    start_y,
    end_x,
    end_y,
    crop_width,
    crop_height,
    frame_count,
    direction='shortest',
    command_file=None,
):
    """Build a fixed-size linear crop across a horizontally wrapping panorama."""
    source_width, source_height, start_x, start_y, end_x, end_y = map(
        int, (source_width, source_height, start_x, start_y, end_x, end_y),
    )
    crop_width, crop_height, frame_count = map(int, (crop_width, crop_height, frame_count))
    direction = str(direction)

    buildPanoramaCropFilter(
        source_width,
        source_height,
        start_x,
        start_y,
        crop_width,
        crop_height,
    )
    buildPanoramaCropFilter(
        source_width,
        source_height,
        end_x,
        end_y,
        crop_width,
        crop_height,
    )

    if frame_count < 2:
        raise ValueError('Panorama pan requires at least two frames')
    if direction not in PANORAMA_PAN_DIRECTIONS:
        raise ValueError('Unsupported panorama pan direction')

    delta_x = _panoramaPanDeltaX(source_width, start_x, end_x, direction)

    if not delta_x and start_y == end_y:
        return buildPanoramaCropFilter(
            source_width,
            source_height,
            start_x,
            start_y,
            crop_width,
            crop_height,
        )

    frame_divisor = frame_count - 1
    needs_horizontal_wrap = (
        min(start_x, start_x + delta_x) < 0
        or max(start_x, start_x + delta_x) + crop_width > source_width
    )
    filter_prefix = ''
    crop_x_base = '({0:d}{1:+d}*n/{2:d})'.format(
        start_x,
        delta_x,
        frame_divisor,
    )
    if needs_horizontal_wrap:
        # Two copies let the crop span the seam; modulo keeps its moving left
        # edge inside the first copy regardless of the chosen route.
        filter_prefix = (
            'split=2[pano_0][pano_1];'
            '[pano_0][pano_1]hstack=inputs=2[pano_strip];'
            '[pano_strip]'
        )
        crop_x_base = 'mod(({0:d}{1:+d}*n/{2:d})+{3:d}\\,{3:d})'.format(
            start_x,
            delta_x,
            frame_divisor,
            source_width,
        )

    if command_file:
        command_path = str(Path(command_file)).replace('\\', '/')
        command_path = command_path.replace(':', '\\:').replace("'", "\\'")
        return (
            "sendcmd=f='{command_file:s}',{prefix}"
            'crop@panorama_pan=w={width:d}:h={height:d}:x={start_x:d}:y={start_y:d}'
        ).format(
            command_file=command_path,
            prefix=filter_prefix,
            width=crop_width,
            height=crop_height,
            start_x=start_x,
            start_y=start_y,
        )

    return (
        '{prefix}crop=w={width:d}:h={height:d}:'
        'x=trunc({x}/2)*2:y=trunc(({start_y:d}{delta_y:+d}*n/{divisor:d})/2)*2'
    ).format(
        prefix=filter_prefix,
        width=crop_width,
        height=crop_height,
        x=crop_x_base,
        start_y=start_y,
        delta_y=end_y - start_y,
        divisor=frame_divisor,
    )


def buildPanoramaTimedPanFilter(
    source_width,
    source_height,
    start_x,
    start_y,
    end_x,
    end_y,
    crop_width,
    crop_height,
    frame_timestamps,
    framerate,
    command_file,
    direction='shortest',
):
    """Build a pan whose surviving frames retain their capture-time positions."""
    frame_count = len(frame_timestamps)
    filter_graph = buildPanoramaPanFilter(
        source_width,
        source_height,
        start_x,
        start_y,
        end_x,
        end_y,
        crop_width,
        crop_height,
        frame_count,
        direction=direction,
        command_file=command_file,
    )

    source_width = int(source_width)
    start_x, start_y, end_x, end_y = map(int, (start_x, start_y, end_x, end_y))
    framerate = float(framerate)
    if not math.isfinite(framerate) or framerate <= 0:
        raise ValueError('Panorama pan framerate must be positive')

    first_timestamp = float(frame_timestamps[0])
    last_timestamp = float(frame_timestamps[-1])
    if not math.isfinite(first_timestamp) or not math.isfinite(last_timestamp):
        raise ValueError('Panorama pan timestamps must be finite')
    timestamp_range = last_timestamp - first_timestamp
    if timestamp_range <= 0:
        raise ValueError('Panorama pan frames must have increasing timestamps')

    delta_x = _panoramaPanDeltaX(source_width, start_x, end_x, direction)

    if not delta_x and start_y == end_y:
        return filter_graph

    previous_timestamp = first_timestamp
    with Path(command_file).open('w', encoding='ascii') as command_f:
        for index, frame_timestamp in enumerate(frame_timestamps):
            timestamp = float(frame_timestamp)
            if not math.isfinite(timestamp):
                raise ValueError('Panorama pan timestamps must be finite')
            if timestamp < previous_timestamp:
                raise ValueError('Panorama pan timestamps must be ordered')
            previous_timestamp = timestamp

            progress = (timestamp - first_timestamp) / timestamp_range
            crop_x = int(((start_x + (delta_x * progress)) % source_width) / 2) * 2
            crop_y = int((start_y + ((end_y - start_y) * progress)) / 2) * 2
            command_time = 0 if not index else (index - 0.5) / framerate
            command_f.write(
                '{0:.9f} crop@panorama_pan x {1:d}, crop@panorama_pan y {2:d};\n'.format(
                    command_time,
                    crop_x,
                    crop_y,
                )
            )

    return filter_graph


def validatePanoramaMiniTimelapseRequest(source_width, source_height, request_data):
    """Normalize and validate the panorama selection received from the browser."""
    try:
        selection = {
            'crop_x'      : int(request_data['CROP_X']),
            'crop_y'      : int(request_data['CROP_Y']),
            'crop_width'  : int(request_data['CROP_WIDTH']),
            'crop_height' : int(request_data['CROP_HEIGHT']),
            'aspect_ratio': str(request_data.get('ASPECT_RATIO', 'free')),
            'pan_mode'    : str(request_data.get('PAN_MODE', 'static')),
        }
    except (KeyError, TypeError, ValueError):
        raise ValueError('Panorama selection is incomplete or invalid')

    buildPanoramaCropFilter(
        source_width,
        source_height,
        selection['crop_x'],
        selection['crop_y'],
        selection['crop_width'],
        selection['crop_height'],
    )
    validatePanoramaAspectRatio(
        selection['aspect_ratio'],
        selection['crop_width'],
        selection['crop_height'],
    )

    if selection['pan_mode'] not in PANORAMA_PAN_MODES:
        raise ValueError('Unsupported panorama pan mode')

    if selection['pan_mode'] == 'linear':
        try:
            selection['end_crop_x'] = int(request_data['END_CROP_X'])
            selection['end_crop_y'] = int(request_data['END_CROP_Y'])
            selection['pan_direction'] = str(request_data.get('PAN_DIRECTION', 'shortest'))
        except (KeyError, TypeError, ValueError):
            raise ValueError('Panorama end selection is incomplete or invalid')

        buildPanoramaCropFilter(
            source_width,
            source_height,
            selection['end_crop_x'],
            selection['end_crop_y'],
            selection['crop_width'],
            selection['crop_height'],
        )
        if selection['pan_direction'] not in PANORAMA_PAN_DIRECTIONS:
            raise ValueError('Unsupported panorama pan direction')
    else:
        selection['end_crop_x'] = selection['crop_x']
        selection['end_crop_y'] = selection['crop_y']
        selection['pan_direction'] = 'shortest'

    return selection


def cropPanoramaArray(image, crop_x, crop_y, crop_width, crop_height):
    """Apply the video crop and seam wrapping rules to an in-memory image."""
    source_height, source_width = image.shape[:2]

    buildPanoramaCropFilter(
        source_width,
        source_height,
        crop_x,
        crop_y,
        crop_width,
        crop_height,
    )

    crop_x, crop_y, crop_width, crop_height = map(
        int, (crop_x, crop_y, crop_width, crop_height),
    )
    crop_end_x = crop_x + crop_width

    if crop_end_x <= source_width:
        return image[
            crop_y:crop_y + crop_height,
            crop_x:crop_end_x,
        ].copy()

    right = image[
        crop_y:crop_y + crop_height,
        crop_x:source_width,
    ]
    left = image[
        crop_y:crop_y + crop_height,
        0:crop_end_x - source_width,
    ]

    return numpy.concatenate((right, left), axis=1)
