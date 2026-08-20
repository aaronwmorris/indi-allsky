from types import SimpleNamespace

import darks as darks_cli


def test_public_cli_surface_and_defaults_match_legacy_tool():
    parser = darks_cli.build_arg_parser()
    public_destinations = {
        action.dest
        for action in parser._actions
        if action.help != darks_cli.argparse.SUPPRESS
    }

    assert public_destinations == {
        'help',
        'action',
        'Count',
        'gains',
        'Binning',
        'temp_delta',
        'Time_delta',
        'bitmax',
        'flush_id',
        'reverse',
        'daytime',
    }
    assert '--automation-manifest' not in parser.format_help()

    args = parser.parse_args(['sigmaclip'])
    assert vars(args) == {
        'action': 'sigmaclip',
        'Count': 10,
        'gains': None,
        'Binning': 1,
        'temp_delta': 5.0,
        'Time_delta': 5,
        'bitmax': 0,
        'flush_id': 1,
        'automation_manifest': None,
        'reverse': True,
        'daytime': True,
    }


def test_legacy_cli_arguments_still_configure_capture_unchanged():
    parser = darks_cli.build_arg_parser()
    args = parser.parse_args([
        'average',
        '--Count', '3',
        '--gains', '0', '200',
        '--Binning', '2',
        '--temp_delta', '2.5',
        '--Time_delta', '10',
        '--bitmax', '16',
        '--flush_id', '7',
        '--no-reverse',
        '--no-daytime',
    ])
    capture = SimpleNamespace()

    darks_cli.configure_legacy_capture(capture, args)

    assert capture == SimpleNamespace(
        count=3,
        gain_list=[0.0, 200.0],
        binning=2,
        temp_delta=2.5,
        time_delta=10,
        bitmax=16,
        flush_camera_id=7,
        reverse=False,
        daytime=False,
    )


def test_private_manifest_configures_targeted_web_capture():
    capture = SimpleNamespace()
    darks_cli.configure_automation_capture(capture, {
        'automation': True,
        'frame_count': 3,
        'capture_order': 'short_first',
        'progress_file': '/tmp/dark-progress.json',
        'capture_period': 'night',
        'binning': 1,
        'bitmax': 16,
        'gains': [0, 200],
        'exposures': [1, 5],
    })

    assert capture.count == 3
    assert capture.reverse is False
    assert capture.progress_file == '/tmp/dark-progress.json'
    assert capture.capture_profile == 'night'
    assert capture.binning == 1
    assert capture.bitmax == 16
    assert capture.gain_list == [0, 200]
    assert capture.exposure_list == [1, 5]


def test_private_manifest_configures_temperature_series():
    capture = SimpleNamespace()
    darks_cli.configure_automation_capture(capture, {
        'automation': True,
        'frame_count': 5,
        'capture_order': 'long_first',
        'progress_file': '/tmp/dark-temperature-progress.json',
        'temperature_series': True,
        'temperature_delta': 2.5,
        'temperature_target': -10,
    })

    assert capture.count == 5
    assert capture.reverse is True
    assert capture.progress_file == '/tmp/dark-temperature-progress.json'
    assert capture.temp_delta == 2.5
    assert capture.temperature_target == -10.0
