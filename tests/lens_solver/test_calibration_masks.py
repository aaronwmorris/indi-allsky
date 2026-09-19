"""Compare solver/browser masks with the capture pipeline across image layouts."""
import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from indi_allsky.lens_solver.detection import StarDetector
from tests.flask.test_virtualsky import run_node


@pytest.fixture(scope='module')
def processor_class():
    # Exercise the actual image transforms without importing camera services.
    path = Path(__file__).resolve().parents[2] / 'indi_allsky/processing.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ImageProcessor')
    methods = ('rotate_90', '_rotate_90', 'rotate_angle', '_rotate_angle', '_flip',
               'flip_h', 'flip_v', 'crop_image', '_crop_image', 'scale_image',
               '_scale_image', 'add_border', '_add_border', '_generate_image_circle_mask')
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    namespace = dict(cv2=cv2, numpy=np, logger=logging.getLogger(__name__))
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['ImageProcessor']


@pytest.mark.parametrize('shape', [(241, 401), (403, 237)])
@pytest.mark.parametrize('binning', [1, 2, 4])
@pytest.mark.parametrize('focus', [False, True])
@pytest.mark.parametrize('transforms', [
    {},
    dict(IMAGE_ROTATE='ROTATE_90_CLOCKWISE', IMAGE_FLIP_H=True,
         IMAGE_CROP_ROI=[20, 10, 180, 200], IMAGE_SCALE=37),
    dict(IMAGE_ROTATE_ANGLE=27, IMAGE_ROTATE_KEEP_SIZE=False, IMAGE_FLIP_V=True,
         IMAGE_CROP_IMAGE_CIRCLE=True, LENS_IMAGE_CIRCLE=130, IMAGE_SCALE=75),
    dict(IMAGE_ROTATE_ANGLE=-17, IMAGE_ROTATE_KEEP_SIZE=True, IMAGE_FLIP_H=True,
         IMAGE_FLIP_V=True, IMAGE_CROP_ROI=[1, 3, 200, 220], IMAGE_SCALE=50),
])
def test_detection_hints_follow_capture_transforms(tmp_path, processor_class, shape, binning, focus, transforms):
    mask = np.zeros(shape, np.uint8)
    mask[shape[0]//5:shape[0]*4//5, shape[1]//7:shape[1]*3//4] = 255
    path = tmp_path / 'sensor-mask.png'
    assert cv2.imwrite(str(path), mask)
    sensor_shape = tuple(n//binning for n in shape)
    config = dict(IMAGE_SCALE=100, FOCUS_MODE=focus, DETECT_MASK=str(path),
                  LENS_OFFSET_X=-13, LENS_OFFSET_Y=15,
                  IMAGE_BORDER=dict(TOP=5, RIGHT=7, BOTTOM=9, LEFT=11))
    config.update(transforms)
    processor = processor_class()
    processor.config, processor.focus_mode = config, focus
    processor.getLatestImage = lambda: SimpleNamespace(binning=binning)
    processor.image = cv2.cvtColor(cv2.resize(mask, sensor_shape[::-1]), cv2.COLOR_GRAY2BGR)
    for operation in ('rotate_90', 'rotate_angle', 'flip_v', 'flip_h', 'crop_image', 'scale_image', 'add_border'):
        getattr(processor, operation)()
    expected = (processor.image[:, :, 0] > 127).astype(np.uint8)*255
    detector = StarDetector(config)
    detector.use_sky_hints, detector.binning = True, binning
    for dimensions in (sensor_shape, None):  # older camera records omit dimensions
        detector.sensor_shape = dimensions
        np.testing.assert_array_equal(detector.buildExclusionMask(expected.shape), expected)


@pytest.mark.parametrize('shape,binning,scale,offset', [
    ((601, 999), 1, 100, (-29, 37)), ((999, 601), 2, 37, (31, -27)),
    ((600, 1000), 4, 75, (-100, -11)), ((333, 777), 1, 1, (15, 11)),
])
def test_browser_circle_tracks_cropped_photo_after_resize(processor_class, shape, binning, scale, offset):
    processor = processor_class()
    processor.focus_mode = False
    processor.config = dict(IMAGE_SCALE=scale, LENS_OFFSET_X=offset[0], LENS_OFFSET_Y=offset[1],
        IMAGE_CIRCLE_MASK=dict(DIAMETER=900, OPACITY=100, OUTLINE=False, BLUR=0),
        IMAGE_BORDER=dict(TOP=13, RIGHT=7, BOTTOM=3, LEFT=19))
    processor.image = processor._generate_image_circle_mask(np.empty(shape), binning)*255
    processor.scale_image()
    processor.add_border()
    height, width = processor.image.shape[:2]
    mask = [900, *offset, scale, 13, 7, 3, 19]
    circle = json.loads(run_node('-e', '''
const {maskImage} = require('./indi_allsky/flask/static/js/virtualsky-calibration.js');
const {mask, size} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const sky = {wide:size[0], tall:1000, drawImmediate() {}, ctx:{
  save(){}, restore(){}, clearRect(){}, beginPath(){}, clip(){},
  arc(x,y,r){ console.log(JSON.stringify([x,y-(1000-size[1])/2,r])); }
}};
maskImage(sky, mask, size, ''' + str(binning) + ''', [1000,0,0]);
sky.drawImmediate();
''', input=json.dumps(dict(mask=mask, size=[width, height]))))
    y, x = np.mgrid[:height, :width]
    distance = np.hypot(x-circle[0], y-circle[1])-circle[2]
    # Capture rounds resize dimensions down to even pixels. The browser knows
    # the final size, so allow that subpixel/raster boundary, not a shifted rim.
    interior = np.zeros((height, width), bool)
    interior[13:height-3, 19:width-7] = True
    assert np.all(processor.image[:, :, 0][interior & (distance < -2)] > 127)
    assert np.all(processor.image[:, :, 0][distance > 2] == 0)
