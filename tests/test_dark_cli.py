import json
import runpy
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

import darks_automation as automation_cli
from indi_allsky.temperature import database_temperature


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _legacy_dark_module(capture_class):
    module = ModuleType('indi_allsky.darks')
    module.IndiAllSkyDarks = capture_class
    return module


def test_legacy_cli_arguments_still_configure_and_run_unchanged(monkeypatch):
    captures = []

    class Capture:
        def __init__(self):
            captures.append(self)

        def average(self):
            self.action = 'average'

    monkeypatch.setitem(sys.modules, 'indi_allsky.darks', _legacy_dark_module(Capture))
    monkeypatch.setattr('locale.setlocale', lambda *args: None)
    monkeypatch.setattr('multiprocessing.set_start_method', lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, 'argv', [
        'darks.py',
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

    runpy.run_path(str(REPOSITORY_ROOT.joinpath('darks.py')), run_name='__main__')

    capture = captures[0]
    assert capture.action == 'average'
    assert capture.count == 3
    assert capture.gain_list == [0.0, 200.0]
    assert capture.binning == 2
    assert capture.temp_delta == 2.5
    assert capture.time_delta == 10
    assert capture.bitmax == 16
    assert capture.flush_camera_id == 7
    assert capture.reverse is False
    assert capture.daytime is False


def test_legacy_cli_help_does_not_expose_web_options(monkeypatch, capsys):
    class Capture:
        pass

    monkeypatch.setitem(sys.modules, 'indi_allsky.darks', _legacy_dark_module(Capture))
    monkeypatch.setattr('locale.setlocale', lambda *args: None)
    monkeypatch.setattr('multiprocessing.set_start_method', lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, 'argv', ['darks.py', '--help'])

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(REPOSITORY_ROOT.joinpath('darks.py')), run_name='__main__')

    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert '--automation-manifest' not in help_text
    assert '--manifest' not in help_text
    assert '--Count' in help_text
    assert '--gains' in help_text


def test_private_manifest_configures_targeted_web_capture():
    capture = SimpleNamespace()

    action = automation_cli.configure_capture(capture, {
        'automation': True,
        'method': 'sigmaclip',
        'frame_count': 3,
        'capture_order': 'short_first',
        'progress_file': '/tmp/dark-progress.json',
        'capture_period': 'night',
        'binning': 1,
        'bitmax': 16,
        'gains': [0, 200],
        'exposures': [1, 5],
    })

    assert action == 'sigmaclip'
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

    action = automation_cli.configure_capture(capture, {
        'automation': True,
        'method': 'average',
        'frame_count': 5,
        'capture_order': 'long_first',
        'progress_file': '/tmp/dark-temperature-progress.json',
        'temperature_series': True,
        'temperature_delta': 2.5,
        'temperature_target': -10,
    })

    assert action == 'tempaverage'
    assert capture.count == 5
    assert capture.reverse is True
    assert capture.progress_file == '/tmp/dark-temperature-progress.json'
    assert capture.temp_delta == 2.5
    assert capture.temperature_target == -10


def test_private_launcher_rejects_non_automation_manifests():
    with pytest.raises(ValueError, match='Invalid automation manifest'):
        automation_cli.configure_capture(SimpleNamespace(), {})


def test_private_launcher_handles_plan_changes_and_installs_signals(monkeypatch, tmp_path):
    class PlanChanged(RuntimeError):
        pass

    class Capture:
        def sigmaclip(self):
            raise PlanChanged()

        def sigint_handler_main(self, signum, frame):
            pass

    dark_module = _legacy_dark_module(Capture)
    dark_module.DarkCapturePlanChanged = PlanChanged
    monkeypatch.setitem(sys.modules, 'indi_allsky.darks', dark_module)
    monkeypatch.setattr(automation_cli.locale, 'setlocale', lambda *args: None)
    monkeypatch.setattr(
        automation_cli.multiprocessing,
        'set_start_method',
        lambda *args, **kwargs: None,
    )
    signals = []
    monkeypatch.setattr(
        automation_cli.signal,
        'signal',
        lambda signum, handler: signals.append((signum, handler)),
    )
    manifest_path = tmp_path.joinpath('manifest.json')
    manifest_path.write_text(json.dumps({
        'automation': True,
        'method': 'sigmaclip',
        'frame_count': 3,
        'progress_file': str(tmp_path.joinpath('progress.json')),
        'capture_period': 'night',
        'binning': 1,
        'gains': [0],
        'exposures': [1],
    }), encoding='utf-8')

    assert automation_cli.main(['--manifest', str(manifest_path)]) == 75
    assert [signum for signum, _handler in signals] == [
        automation_cli.signal.SIGINT,
        automation_cli.signal.SIGTERM,
    ]


def test_builder_temperature_storage_opt_in_does_not_change_legacy_default():
    assert database_temperature(0) is None
    assert database_temperature(0, preserve_zero=True) == 0.0
    assert database_temperature(-5) == -5.0
    assert database_temperature(None, preserve_zero=True) is None
