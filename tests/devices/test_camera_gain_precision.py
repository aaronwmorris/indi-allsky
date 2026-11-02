"""Camera precision is available without another experimental feature."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest


def reported_gain(driver):
    source = Path(__file__).resolve().parents[2] / 'indi_allsky/camera/indi.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'IndiClient')
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'getCcdGain']
    namespace = {'logger': logging.getLogger(__name__), 'TimeOutException': TimeoutError}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), 'exec'), namespace)
    client = namespace['IndiClient']()
    fractional = {'min': 1, 'max': 16, 'step': 1, 'current': 1.875}
    client.ccd_device = SimpleNamespace(getDriverExec=lambda: driver, getCcdGain=lambda: fractional)
    client._IndiClient__canon_gain_to_iso = {}
    client._IndiClient__canon_iso_to_gain = {}
    client._IndiClient__map_indexes = lambda *args: {'Gain': 0, 'GAIN': 0}
    def control(device, name, kind, **kwargs):
        if kind == 'switch':
            return [SimpleNamespace(getLabel=lambda g=g: str(g), getName=lambda g=g: 'ISO' + str(g))
                    for g in [100, 200, 400, 800]]
        return [SimpleNamespace(min=0, max=600, step=60, format='%0.0f', getValue=lambda: 85.912)]
    client.get_control = control
    return client.getCcdGain()


@pytest.mark.parametrize('driver', [
    'indi_asi_ccd', 'indi_asi_single_ccd', 'indi_playerone_ccd', 'indi_playerone_single_ccd',
    'indi_svbony_ccd', 'indi_svbonycam_ccd', 'indi_sv305_ccd',
    'indi_toupcam_ccd', 'indi_altair_ccd', 'indi_altaircam_ccd', 'indi_nncam_ccd',
    'indi_tscam_ccd', 'indi_ogmacam_ccd', 'indi_omegonprocam_ccd',
])
def test_integer_command_resolution_is_distinct_from_gui_step(driver):
    info = reported_gain(driver)
    assert info['quantum'] == 1
    assert info['step'] == 60


@pytest.mark.parametrize('driver', ['indi_qhy_ccd', 'indi_libcamera_ccd', 'indi_pylibcamera',
                                   'libcamera-still', 'rpicam-still', 'indi_sx_ccd'])
def test_fractional_and_no_gain_interfaces_are_not_assumed_integer(driver):
    assert not reported_gain(driver).get('quantum')


@pytest.mark.parametrize('driver', ['indi_gphoto_ccd', 'indi_canon_ccd', 'indi_nikon_ccd',
                                   'indi_pentax_ccd', 'indi_sony_ccd'])
def test_iso_interfaces_report_their_available_commands(driver):
    assert reported_gain(driver)['values'] == [100, 200, 400, 800]
