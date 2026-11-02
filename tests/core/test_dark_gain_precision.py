"""Dark planning and captures resolve gains without optional image features."""
import ast
import logging
from multiprocessing import Array
from pathlib import Path
from types import SimpleNamespace

import pytest

from indi_allsky import exposure as modes
from indi_allsky.capture_state import CameraCapabilities, build_effective_capture_state
from test_dark_library import _config


ROOT = Path(__file__).resolve().parents[2] / 'indi_allsky'


def capabilities(quantum=1, values=()):
    return CameraCapabilities.from_ccd_info({'GAIN_INFO': {
        'min': 0, 'max': 600, 'step': 60, 'quantum': quantum, 'values': list(values),
    }})


def controller(name, caps):
    obj = getattr(modes, name)(_config(name), Array('i', 7), Array('i', 10), Array('i', 6), Array('i', [1, 0]))
    obj._dark_gain = caps.snap_gain
    u = obj._expUtils
    u.EXPOSURE_MIN_DAY = u.EXPOSURE_MIN_NIGHT = .001
    u.EXPOSURE_MAX = 30
    u.GAIN_MIN_NIGHT = 0
    u.GAIN_MAX_NIGHT = 300
    u.BINNING_DAY = u.BINNING_NIGHT = u.BINNING_MOONMODE = 1
    return obj


@pytest.mark.parametrize('quantum,expected', [(1, 86), (0, 85.912)])
def test_camera_precision_survives_database_snapshot_and_planning(quantum, expected):
    caps = capabilities(quantum)
    restored = CameraCapabilities.from_camera(SimpleNamespace(data={'camera_capabilities': caps.to_dict()}))
    config = _config()
    config['CCD_CONFIG']['NIGHT']['GAIN'] = 85.912
    state = build_effective_capture_state(config, restored)
    assert state.profiles[0].gain_min == expected
    assert restored.snap_gain(85.912) == expected


@pytest.mark.parametrize('quantum,values', [(1, ()), (0, ()), (0, (0, 100, 200, 300))])
def test_legacy_live_ladder_matches_dark_plan_and_recognizes_applied_gain(quantum, values, caplog):
    caps = capabilities(quantum, values)
    obj = controller('exposure_legacy_autogain', caps)
    obj.post_init()
    plan = build_effective_capture_state(obj.config, caps)
    assert tuple(obj.auto_gain_step_list) == plan.profiles[0].gain_values
    captured = obj.auto_gain_step_list[0]
    for high in obj.auto_gain_step_list[1:]:
        obj.recalculate_exposure(29.5, captured, 30, 60, 50, 70, 1)
        assert obj._expUtils.GAIN_NEXT == pytest.approx(high, abs=.001001)
        assert obj._expUtils.GAIN_DELTA == pytest.approx(high - captured, abs=.001001)
        captured = obj._expUtils.GAIN_NEXT
    assert 'Current gain not found' not in caplog.text


@pytest.mark.parametrize('name', modes.__all__)
def test_live_auto_exposure_publishes_supported_commands(name):
    obj = controller(name, capabilities())
    gain = 300 if name == 'exposure_basic' else 86
    obj.recalculate_exposure(29.5, gain, 30, 60, 50, 70, 1)
    assert obj._expUtils.GAIN_NEXT == round(obj._expUtils.GAIN_NEXT)
    assert obj._expUtils.GAIN_DELTA == pytest.approx(obj._expUtils.GAIN_NEXT - gain, abs=.001)


def test_close_fractional_ladder_steps_prefer_the_exact_current_gain():
    obj = controller('exposure_legacy_autogain', capabilities(0))
    obj._expUtils.GAIN_MAX_NIGHT = .005
    obj.post_init()
    for gain in obj.auto_gain_step_list[:-1]:
        obj.recalculate_exposure(29.5, gain, 30, 60, 50, 70, 1)
        assert obj._expUtils.GAIN_NEXT > gain


@pytest.mark.parametrize('info,requested,expected', [
    ({'min': 0, 'max': 600, 'quantum': 1}, 85.912, 86),
    ({'min': 0, 'max': 600}, 85.912, 85.912),
    ({'min': 100, 'max': 800, 'values': [100, 200, 400, 800]}, 385.9, 400),
    ({'min': -1, 'max': -1}, -1, -1),
])
def test_dark_camera_command_and_startup_current_pending_use_planned_gain(info, requested, expected):
    source = (ROOT / 'darks.py').read_text(encoding='utf-8')
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'IndiAllSkyDarks')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'shoot')
    namespace = {'CameraCapabilities': CameraCapabilities, 'logger': logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'dark-shoot', 'exec'), namespace)
    sent = []
    worker = SimpleNamespace(ccd_info={'GAIN_INFO': info}, indiclient=SimpleNamespace(
        setCcdExposure=lambda exposure, gain, binning, **kw: sent.append(gain)))
    namespace['shoot'](worker, 1, requested, 1)
    assert sent == [expected]
    source = (ROOT / 'capture.py').read_text(encoding='utf-8')
    initialize = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == '_initialize')
    assignments = [n for n in initialize.body if isinstance(n, ast.Assign)
                   and (ast.unparse(n).startswith('ccd_gain_default = gain_normalizer(')
                        or ast.unparse(n.targets[0]) in ('self._expUtils.GAIN_CURRENT', 'self._expUtils.GAIN_NEXT'))]
    assert len(assignments) == 3
    worker._expUtils = SimpleNamespace()
    namespace.update(self=worker, ccd_gain_default=requested,
                     gain_normalizer=CameraCapabilities.from_ccd_info(worker.ccd_info).snap_gain)
    exec(compile(ast.Module(body=assignments, type_ignores=[]), 'capture-startup', 'exec'), namespace)
    assert worker._expUtils.GAIN_CURRENT == worker._expUtils.GAIN_NEXT == expected
