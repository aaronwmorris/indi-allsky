"""Geographic labels and panorama geometry in the final, processed image."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from indi_allsky.overlay.cardinalDirsLabel import IndiAllskyCardinalDirsLabel


ROOT = Path(__file__).resolve().parents[2]


def load_methods(filename, class_name, *names):
    # Exercise the pipeline methods without initializing a camera or a Flask DB.
    path = ROOT / 'indi_allsky' / filename
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    cls.bases = []
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(numpy=np, cv2=cv2, math=math, __package__='indi_allsky.flask' if filename.startswith('flask/') else 'indi_allsky')
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[class_name]()


@pytest.fixture
def config():
    return {
        'IMAGE_FLIP_V': True, 'IMAGE_FLIP_H': True, 'IMAGE_LABEL_SYSTEM': 'opencv',
        'CARDINAL_DIRS': {'ENABLE': True, 'AUTO_ALIGN': True, 'CHAR_EAST': 'O',
                         'SWAP_NS': True, 'SWAP_EW': True, 'FONT_COLOR': [255, 255, 255],
                         'OFFSET_TOP': 12, 'OFFSET_LEFT': 12, 'OFFSET_RIGHT': 28, 'OFFSET_BOTTOM': 12},
        'TEXT_PROPERTIES': {'FONT_FACE': 'FONT_HERSHEY_SIMPLEX', 'FONT_AA': 'LINE_AA',
                            'FONT_OUTLINE': False, 'FONT_THICKNESS': 1},
        'FISH2PANO': {'DIAMETER': 300, 'SCALE': 0.51, 'ROTATE_ANGLE': 89, 'FLIP_H': True},
    }


def test_pending_labels_are_suppressed_and_solved_characters_follow_final_pixels(config):
    proc = load_methods('processing.py', 'ImageProcessor', 'cardinal_dirs_label')
    proc.config, proc.focus_mode = config, False
    proc._cardinal_dirs_label = IndiAllskyCardinalDirsLabel(config)
    proc.image = np.zeros((180, 320, 3), np.uint8)
    proc.cardinal_dirs_label()
    assert not np.any(proc.image)
    coords = {'N': (.12, .60), 'E': (.63, .12), 'S': (.86, .60), 'W': (.5, .90)}
    proc.cardinal_dirs_label({'directions': coords})
    for x, y in coords.values():
        col, row = round(x * 320), round(y * 180)
        assert proc.image[row-20:row+2, col:col+20].any()

    drawn = {}
    proc._cardinal_dirs_label.applyLabels_opencv = lambda image, labels: drawn.update(labels) or image
    proc.cardinal_dirs_label({'directions': coords})
    assert drawn == {'N': (38, 108), 'O': (202, 22), 'S': (275, 108), 'W': (160, 162)}
    config['CARDINAL_DIRS']['AUTO_ALIGN'] = False
    drawn.clear()
    proc.cardinal_dirs_label()
    assert set(drawn) == {'N', 'S', 'O', 'W'} and drawn['N'] != (38, 108)


@pytest.mark.parametrize('flip,angle', [(False, 0), (True, 89)])
def test_geographic_panorama_pixels_and_labels_share_true_north_seam(config, flip, angle):
    config['FISH2PANO'].update(FLIP_H=flip, ROTATE_ANGLE=angle, DIRS_OFFSET_BOTTOM=10)
    proc = load_methods('processing.py', 'ImageProcessor', 'fish2pano', 'fish2pano_cardinal_dirs_label')
    proc.config = config
    proc._cardinal_dirs_label = IndiAllskyCardinalDirsLabel(config)
    native = np.zeros((201, 301, 3), np.uint8)
    colors = [(11, 22, 250), (32, 240, 20), (238, 25, 22), (28, 250, 223)]
    for pos, color in zip([(150, 50), (100, 100), (150, 150), (200, 100)], colors):
        cv2.circle(native, pos, 5, color, -1)
    pano = proc.fish2pano(1, native)
    height, width = pano.shape[:2]
    assert height == 76 and width == 480
    for i, color in enumerate(colors):
        assert np.all(pano[height//2, i*width//4] == color)
    assert np.all(pano[height//2, -1] == colors[0])  # north wraps at the seam
    drawn = {}
    proc._cardinal_dirs_label.panorama_label_opencv = lambda image, labels: drawn.update(labels) or image
    proc.fish2pano_cardinal_dirs_label(pano, geographic=True)
    assert drawn == {label: (i*width//4, height-10) for i, label in enumerate(('N', 'O', 'S', 'W'))}


def test_geometry_written_to_archive_and_sync_obeys_privacy():
    worker = load_methods('image.py', 'ImageWorker', 'alignment_metadata')
    private = {'id': 'test-solve', 'location': [52.4937, 13.41591]}
    worker.star_alignment = SimpleNamespace(solution=private)
    worker.config = {'PRIVACY_MODE': True}
    assert worker.alignment_metadata() == {'id': 'test-solve', 'location': [52, 13]}
    assert private['location'] == [52.4937, 13.41591]
    worker.config['PRIVACY_MODE'] = False
    assert worker.alignment_metadata() == private
    worker.star_alignment.solution = None
    assert worker.alignment_metadata() is None


def test_rotated_tilted_native_frame_and_resized_borders_feed_the_same_panorama(config):
    from indi_allsky.aligned_media import SkyRemap
    from indi_allsky.fisheye import SIN45, projectToPixels

    # Solver coordinates refer to the final archived frame. The panorama is
    # sampled from the intermediate frame before odd-sized borders and scaling.
    width, height = 640, 480
    final_w, final_h = 345, 260
    left, top, right, bottom = 8, 6, 17, 14
    assert (final_w-left-right, final_h-top-bottom) == (width//2, height//2)
    roll, diameter, dx, dy, curve, altitude, pointing = (74, 190, 7, -6, .12, 73, 118)
    values = dict(AZIMUTH_ANGLE=roll, LENS_ALTITUDE=altitude, POINTING_AZIMUTH=pointing,
                  IMAGE_CIRCLE_DIAMETER=diameter, OFFSET_X=dx, OFFSET_Y=dy, RADIAL_DISTORTION=curve)
    solution = {'image_size': [final_w, final_h], 'values': values}
    altitude_rad = math.radians(30.)
    x, y = projectToPixels(altitude_rad, np.radians([0, 90, 180, 270]),
                           [roll, 0, 0, diameter, dx, dy, curve], final_w, final_h,
                           lens_altitude=altitude, pointing_azimuth=pointing)
    native = np.zeros((height, width, 3), np.uint8)
    colors = [(11, 22, 250), (32, 240, 20), (238, 25, 22), (28, 250, 223)]
    for px, py, color in zip(x, y, colors):
        cv2.circle(native, (round((px-left+.5)*2-.5), round((py-top+.5)*2-.5)), 8, color, -1)
    canonical = SkyRemap().image(native, solution, border=(left, top, right, bottom))
    proc = load_methods('processing.py', 'ImageProcessor', 'fish2pano')
    proc.config = config
    pano = proc.fish2pano(1, canonical)
    ph, pw = pano.shape[:2]
    row = round(ph * math.sin((math.pi/2-altitude_rad)/2) / SIN45)
    for i, color in enumerate(colors):
        assert np.array_equal(pano[row, i*pw//4], color)


def test_longterm_uses_original_rgb_at_geographic_sample_points():
    proc = load_methods('image.py', 'ImageWorker', 'save_longterm_keogram_data')
    rng = np.random.default_rng(135)
    native = rng.integers(0, 255, (90, 110, 3), dtype=np.uint8)
    proc.image_processor = SimpleNamespace(focus_mode=False, image=np.zeros_like(native))
    proc.config = {'LONGTERM_KEOGRAM': {'OFFSET_X': 3, 'OFFSET_Y': 2}}
    calls = []
    proc._miscDb = SimpleNamespace(add_long_term_keogram_data=lambda *args: calls.append(args))
    y, x = np.mgrid[:90, :110].astype(np.float32)
    maps = cv2.convertMaps(109.2 - x, 89.1 - y, cv2.CV_16SC2)
    reference = cv2.remap(native, *maps, cv2.INTER_LINEAR)
    expected = reference[43:48, 58, ::-1].tolist()
    assert proc.save_longterm_keogram_data(132., 1, native, maps) == expected
    assert calls == [(132., 1, expected)]


def test_horizon_clipping_uses_the_solved_horizon_and_excludes_the_border():
    proc = load_methods('processing.py', 'ImageProcessor', 'geographic_horizon_clipped', 'image_border')
    proc.config = {'IMAGE_BORDER': {'LEFT': 40, 'RIGHT': 40}, 'FISH2PANO': {'DIAMETER': 1234}}
    values = dict(LENS_ALTITUDE=90, POINTING_AZIMUTH=0, AZIMUTH_ANGLE=45, IMAGE_CIRCLE_DIAMETER=200,
                  OFFSET_X=0, OFFSET_Y=0, RADIAL_DISTORTION=0)
    solution = {'image_size': [300, 200], 'values': values}
    assert not proc.geographic_horizon_clipped(solution)
    values['OFFSET_X'] = 25
    assert proc.geographic_horizon_clipped(solution)
    values.update(OFFSET_X=0, LENS_ALTITUDE=60, POINTING_AZIMUTH=0)
    assert proc.geographic_horizon_clipped(solution)


def test_fits_preview_only_reuses_geometry_for_the_exact_frame_and_pipeline(config):
    from unittest.mock import Mock
    from indi_allsky.lens_solver.calibration import pipelineSignature

    preview = load_methods('flask/views.py', 'JsonImageProcessingView', 'preview_alignment')
    proc = load_methods('processing.py', 'ImageProcessor', 'image_border', 'scaled_size')
    proc.config = dict(config, IMAGE_SCALE=50, IMAGE_BORDER={'LEFT': 4, 'TOP': 1, 'RIGHT': 2, 'BOTTOM': 3})
    proc.image = np.zeros((200, 320, 3), np.uint8)
    fits = SimpleNamespace(camera_id=9, createDate=123, dayDate=135)
    directions = {'N': [0.5, 0], 'S': [0.5, 1], 'E': [0, 0.5], 'W': [1, 0.5]}
    stored = {'pipeline': pipelineSignature(proc.config), 'directions': directions}
    entry = SimpleNamespace(data={'star_alignment': stored})
    model = Mock()
    ns = preview.preview_alignment.__globals__
    ns['IndiAllSkyDbImageTable'] = model
    ns['virtualsky_frame_alignment'] = lambda view, e: {'image_size': [166,104]}
    query = model.query.filter_by.return_value.limit.return_value
    query.all.return_value = [entry]
    geometry, msg = preview.preview_alignment(fits, proc)
    assert geometry['directions'] == directions and 'Aligned by stars' in msg
    model.query.filter_by.assert_called_once_with(camera_id=9, createDate=123, dayDate=135)
    proc.config['IMAGE_FLIP_H'] = not proc.config['IMAGE_FLIP_H']
    geometry, msg = preview.preview_alignment(fits, proc)
    assert geometry is None and 'differs' in msg  # a mirror keeps identical dimensions
    query.all.return_value = [entry, entry]
    assert preview.preview_alignment(fits, proc)[0] is None
    query.all.return_value = []
    assert preview.preview_alignment(fits, proc)[0] is None
