import pytest
from indi_allsky.panorama import (
    panoramaSourceCircleClipped,
    buildPanoramaCropFilter,
    buildPanoramaPanFilter,
    buildPanoramaTimedPanFilter,
    validatePanoramaMiniTimelapseRequest,
    _panoramaPanDeltaX,
)


def test_panorama_source_circle_clipped_invalid_dimensions():
    with pytest.raises(ValueError, match="Panorama source and circle dimensions must be positive"):
        panoramaSourceCircleClipped(0, 100, 50)
    with pytest.raises(ValueError, match="Panorama source and circle dimensions must be positive"):
        panoramaSourceCircleClipped(100, 0, 50)
    with pytest.raises(ValueError, match="Panorama source and circle dimensions must be positive"):
        panoramaSourceCircleClipped(100, 100, 0)


def test_build_panorama_crop_filter_small_dimensions():
    with pytest.raises(ValueError, match="Panorama source dimensions must be at least 2 x 2 pixels"):
        buildPanoramaCropFilter(1, 10, 0, 0, 10, 10)
    with pytest.raises(ValueError, match="Panorama source dimensions must be at least 2 x 2 pixels"):
        buildPanoramaCropFilter(10, 1, 0, 0, 10, 10)


def test_panorama_pan_delta_x_shortest():
    # direct_delta_x > source_width / 2
    delta = _panoramaPanDeltaX(100, 10, 90, 'shortest')
    assert delta == -20

    # direct_delta_x < -(source_width / 2)
    delta = _panoramaPanDeltaX(100, 90, 10, 'shortest')
    assert delta == 20


def test_build_panorama_pan_filter_invalid_direction():
    with pytest.raises(ValueError, match="Unsupported panorama pan direction"):
        buildPanoramaPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_count=10,
            direction='invalid_direction',
        )


def test_build_panorama_timed_pan_filter_invalid_framerate(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    with pytest.raises(ValueError, match="Panorama pan framerate must be positive"):
        buildPanoramaTimedPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_timestamps=[1.0, 2.0],
            framerate=0,
            command_file=cmd_file,
        )


def test_build_panorama_timed_pan_filter_non_finite_timestamps(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    with pytest.raises(ValueError, match="Panorama pan timestamps must be finite"):
        buildPanoramaTimedPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_timestamps=[float('nan'), 2.0],
            framerate=24,
            command_file=cmd_file,
        )


def test_build_panorama_timed_pan_filter_decreasing_or_equal_range(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    with pytest.raises(ValueError, match="Panorama pan frames must have increasing timestamps"):
        buildPanoramaTimedPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_timestamps=[2.0, 1.0],
            framerate=24,
            command_file=cmd_file,
        )


def test_build_panorama_timed_pan_filter_no_delta(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    res = buildPanoramaTimedPanFilter(
        source_width=100,
        source_height=100,
        start_x=10,
        start_y=10,
        end_x=10,
        end_y=10,
        crop_width=50,
        crop_height=50,
        frame_timestamps=[1.0, 2.0],
        framerate=24,
        command_file=cmd_file,
    )
    assert "crop=w=50:h=50:x=10:y=10" in res


def test_build_panorama_timed_pan_filter_intermediate_non_finite(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    with pytest.raises(ValueError, match="Panorama pan timestamps must be finite"):
        buildPanoramaTimedPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_timestamps=[1.0, float('nan'), 3.0],
            framerate=24,
            command_file=cmd_file,
        )


def test_build_panorama_timed_pan_filter_unordered_intermediate(tmp_path):
    cmd_file = tmp_path / "cmd.txt"
    with pytest.raises(ValueError, match="Panorama pan timestamps must be ordered"):
        buildPanoramaTimedPanFilter(
            source_width=100,
            source_height=100,
            start_x=0,
            start_y=0,
            end_x=10,
            end_y=0,
            crop_width=50,
            crop_height=50,
            frame_timestamps=[1.0, 0.5, 3.0],
            framerate=24,
            command_file=cmd_file,
        )


def test_validate_panorama_mini_timelapse_request_invalid_pan_mode():
    data = {
        'CROP_X': 0,
        'CROP_Y': 0,
        'CROP_WIDTH': 50,
        'CROP_HEIGHT': 50,
        'PAN_MODE': 'unsupported_mode',
    }
    with pytest.raises(ValueError, match="Unsupported panorama pan mode"):
        validatePanoramaMiniTimelapseRequest(100, 100, data)
