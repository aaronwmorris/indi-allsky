import ast
from pathlib import Path

import cv2
import numpy
import pytest

from indi_allsky import constants


@pytest.fixture
def processor():
    # Run the actual color-processing methods without camera/database services.
    source = (Path(__file__).resolve().parents[2] / 'indi_allsky/processing.py').read_text(encoding='utf-8')
    cls = next(node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == 'ImageProcessor')
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in (
        'white_balance_mtf', '_white_balance_mtf', '_generate_white_balance_lut')]
    namespace = dict(cv2=cv2, numpy=numpy, constants=constants)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'processing-mtf-methods', 'exec'), namespace)
    obj = namespace['ImageProcessor']()
    obj.focus_mode = False
    obj.night_av = [False, False]
    obj._wb_mtf_night = None
    obj._wbb_mtf_lut = obj._wbg_mtf_lut = obj._wbr_mtf_lut = None
    obj.config = {
        'WBB_MTF_MIDTONES': 0.2, 'WBG_MTF_MIDTONES': 0.3, 'WBR_MTF_MIDTONES': 0.4,
        'WBB_MTF_MIDTONES_DAY': 0.6, 'WBG_MTF_MIDTONES_DAY': 0.7, 'WBR_MTF_MIDTONES_DAY': 0.8,
    }
    return obj


@pytest.mark.parametrize('use_night_color', [False, True, None])
def test_mtf_uses_selected_color_profile_across_day_night_transitions(processor, use_night_color):
    if use_night_color is not None:
        processor.config['USE_NIGHT_COLOR'] = use_night_color

    for night in (True, False, False, True):
        processor.night_av[constants.NIGHT_NIGHT] = night
        processor.image = numpy.full((1, 1, 3), 128, dtype=numpy.uint8)
        processor.white_balance_mtf()
        expected = [102, 76, 51] if not night and use_night_color is False else [204, 178, 153]
        numpy.testing.assert_array_equal(processor.image[0, 0], expected)


@pytest.mark.parametrize('explicit_defaults', [False, True])
def test_neutral_day_profile_does_not_apply_non_neutral_night_balance(processor, explicit_defaults):
    processor.config['USE_NIGHT_COLOR'] = False
    for channel in ('B', 'G', 'R'):
        key = 'WB{0}_MTF_MIDTONES_DAY'.format(channel)
        if explicit_defaults:
            processor.config[key] = 0.5
        else:
            processor.config.pop(key)
    original = numpy.array([[[0, 128, 255], [40, 80, 160]]], dtype=numpy.uint8)
    processor.image = original.copy()
    processor.white_balance_mtf()
    numpy.testing.assert_array_equal(processor.image, original)
