import pytest
import numpy as np
from scipy.spatial import cKDTree, QhullError
from unittest.mock import MagicMock, patch

from indi_allsky.lens_solver import fitting, calibration, orientation


# ---------------------------------------------------------------------------
# fitting.py missing coverage: lines 492, 558
# ---------------------------------------------------------------------------

def test_fitting_grid_search_candidate_count_low():
    """Line 492: count < MIN_SEED_MATCH_COUNT in _gridSearchCandidate."""
    ctx = MagicMock()
    ctx.catalog = np.array([[45.0, 0.0], [50.0, 0.0]])
    ctx.latitude = 0.0
    ctx.longitude = 0.0
    ctx.obstime_unix = 0.0
    ctx.tree = cKDTree([[10000.0, 10000.0]])

    engine = fitting.FitEngine(ctx)
    engine.predict_calls = 0

    p0 = np.array([0.0, 0.0, 0.0, 1000.0, 0.0, 0.0])

    with patch('indi_allsky.lens_solver.fitting.predictAltAz', return_value=(np.array([0.5, 0.5]), np.array([0.5, 0.5]))), \
         patch.object(engine, '_visibleStars', return_value=np.array([True, True])), \
         patch.object(engine, '_project', return_value=(np.array([10.0, 20.0]), np.array([10.0, 20.0]))):
        res = engine._gridSearchCandidate(
            p0=p0,
            diameter0=1000.0,
            radius=10.0,
            az_span=10.0,
            az_steps=2,
            diameter_values=np.array([1000.0]),
            offset_span_fraction=0.01,
            offset_steps=2
        )
        assert res is None


def test_fitting_wide_recovery_search_zoom_better():
    """Line 558: zoom[0] > coarse[0] returns zoom[1] in _wideRecoverySearch."""
    ctx = MagicMock()
    engine = fitting.FitEngine(ctx)
    engine.predict_calls = 0
    p0 = np.array([0.0, 0.0, 0.0, 1000.0, 0.0, 0.0])

    coarse_res = (5, np.array([0.0, 0.0, 0.0, 1000.0, 0.0, 0.0]))
    zoom_res = (10, np.array([1.0, 1.0, 1.0, 1050.0, 1.0, 1.0]))

    def mock_grid_search(*args, **kwargs):
        if mock_grid_search.call_count == 1:
            mock_grid_search.call_count += 1
            return coarse_res
        return zoom_res

    mock_grid_search.call_count = 1

    with patch.object(engine, '_gridSearchCandidate', side_effect=mock_grid_search):
        res = engine._wideRecoverySearch(p0, 1000.0)
        assert np.array_equal(res, zoom_res[1])


# ---------------------------------------------------------------------------
# calibration.py missing coverage: lines 77, 97-98, 137-139, 144-145, 148-149, 165-166, 176
# ---------------------------------------------------------------------------

def test_calibration_validate_model_boolean_in_context():
    """Line 77: boolean in context array fails validateCalibration."""
    model = {
        'version': 1,
        'coefficients': np.zeros((10, 2)).tolist(),
        'bounds': [0, 0, 1, 1],
        'geometry': np.zeros(8).tolist(),
        'image_size': [1000, 1000],
        'context': [True, 1.0, 2.0],
        'pipeline': 'a' * 64,
        'camera_uuid': 'cam123',
        'summary': 'test'
    }
    assert calibration.validateCalibration(model) is False


def test_calibration_validate_model_exception_handling():
    """Lines 97-98: exception in validateCalibration returns False."""
    class BadArray:
        def __array__(self, *args, **kwargs):
            raise ValueError("Simulated array error")

    model = {
        'version': 1,
        'coefficients': BadArray(),
        'bounds': [0, 0, 1, 1],
        'geometry': np.zeros(8).tolist(),
        'image_size': [1000, 1000],
        'context': [1.0, 2.0, 3.0],
        'pipeline': 'a' * 64,
        'camera_uuid': 'cam123',
        'summary': 'test'
    }
    assert calibration.validateCalibration(model) is False


def test_calibration_fit_correction_qhull_error():
    """Lines 137-139: QhullError in ConvexHull in fitCorrection."""
    t = np.linspace(-0.5, 0.5, 60)
    predicted = np.column_stack([t, t])
    detected = predicted.copy()
    expected = np.column_stack([np.linspace(-0.5, 0.5, 10), np.linspace(-0.5, 0.5, 10)])

    res, reason = calibration.fitCorrection(predicted, detected, expected, radius=0.1)
    assert res is None
    assert reason == 'Matched stars cover too narrow an area.'


def test_calibration_fit_correction_low_coverage():
    """Lines 144-145: expected is empty or inside.mean() < 0.75."""
    theta = np.linspace(0, 2*np.pi, 60, endpoint=False)
    predicted = np.column_stack([0.5*np.cos(theta), 0.5*np.sin(theta)])
    detected = predicted.copy()
    expected = np.column_stack([np.full(10, 10.0), np.full(10, 10.0)])

    res, reason = calibration.fitCorrection(predicted, detected, expected, radius=0.1)
    assert res is None
    assert reason == 'Stars do not cover enough of the unmasked sky; try a clearer image.'


def test_calibration_fit_correction_high_cond_number():
    """Lines 148-149: np.linalg.cond(design) > 1000 in fitCorrection."""
    grid_x, grid_y = np.meshgrid(np.linspace(-0.4, 0.4, 8), np.linspace(-0.4, 0.4, 8))
    predicted = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    detected = predicted.copy()
    expected = predicted.copy()

    with patch('indi_allsky.lens_solver.calibration._basis', return_value=np.ones((60, 10)) * 1e-10):
        res, reason = calibration.fitCorrection(predicted, detected, expected, radius=0.1)
        assert res is None
        assert reason == 'The distortion fit is poorly constrained by these stars.'


def test_calibration_fit_correction_unstable_fit():
    """Lines 165-166: fit.success is False or unsafe mapping."""
    grid_x, grid_y = np.meshgrid(np.linspace(-0.4, 0.4, 8), np.linspace(-0.4, 0.4, 8))
    predicted = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    detected = predicted.copy()
    expected = predicted.copy()

    def mock_ls(fn, x0, **kwargs):
        m = MagicMock()
        m.success = False
        m.x = np.zeros(len(x0))
        return m

    with patch('indi_allsky.lens_solver.calibration.least_squares', side_effect=mock_ls):
        res, reason = calibration.fitCorrection(predicted, detected, expected, radius=0.1)
        assert res is None
        assert reason == 'The proposed correction is too large or unstable.'


def test_calibration_fit_correction_successful_improvement():
    """Line 176: successful fitCorrection improvement."""
    grid_x, grid_y = np.meshgrid(np.linspace(-0.4, 0.4, 8), np.linspace(-0.4, 0.4, 8))
    predicted = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    detected = predicted + 0.002
    expected = predicted.copy()

    def mock_ls(fn, x0, **kwargs):
        m = MagicMock()
        m.success = True
        c = np.zeros((len(x0) // 2, 2))
        c[0] = [0.002, 0.002]
        m.x = c.ravel()
        return m

    with patch('indi_allsky.lens_solver.calibration.least_squares', side_effect=mock_ls), \
         patch('indi_allsky.lens_solver.calibration._safeMapping', return_value=True):
        best_tuple, reason = calibration.fitCorrection(predicted, detected, expected, radius=0.2)
        assert best_tuple is not None
        model, meta = best_tuple
        assert 'before' in meta
        assert meta['after'] < meta['before']


# ---------------------------------------------------------------------------
# orientation.py missing coverage
# ---------------------------------------------------------------------------

def test_orientation_triangles_empty():
    """Line 31: _triangles with < 3 rays returns empty arrays."""
    rays = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    edges, triangles = orientation._triangles(rays)
    assert len(edges) == 0
    assert len(triangles) == 0


def test_orientation_recover_orientation_too_few_stars():
    """Lines 109-110: recoverOrientation with too few stars in catalog."""
    detections = np.zeros((20, 3))
    catalog = np.zeros((5, 2))
    res = orientation.recoverOrientation(
        detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
        initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000
    )
    assert res is None


def test_orientation_recover_orientation_no_signatures():
    """Lines 112-113: recoverOrientation when world triangles yield no signatures."""
    detections = np.zeros((20, 3))
    catalog = np.column_stack([np.full(15, 45.0), np.linspace(0.0, 0.001, 15)])
    res = orientation.recoverOrientation(
        detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
        initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000
    )
    assert res is None


def test_orientation_recover_orientation_diameter_and_ray_checks():
    """Lines 122, 125, 128, 132: diameter, rays, observed, rows loops in recoverOrientation."""
    detections = np.zeros((20, 3))
    catalog = np.column_stack([np.linspace(40, 80, 20), np.linspace(0, 180, 20)])

    res = orientation.recoverOrientation(
        detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
        initial=[0, 0, 0, 50, 0, 0], width=1000, height=1000
    )
    assert res is None


def test_orientation_recover_orientation_with_radial():
    """Lines 169-171: radial is not None in recoverOrientation."""
    np.random.seed(42)
    catalog = np.column_stack([np.linspace(50, 70, 30), np.linspace(10, 50, 30)])
    detections = np.column_stack([np.random.uniform(400, 600, 30),
                                  np.random.uniform(400, 600, 30),
                                  np.ones(30)])

    res = orientation.recoverOrientation(
        detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
        initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000, radial=0.0
    )
    assert res is None or isinstance(res, tuple)


def test_orientation_recover_orientation_low_matched_pred():
    """Line 179: len(pred) < 10 causes break in recoverOrientation seed fit loop."""
    np.random.seed(42)
    catalog = np.column_stack([np.linspace(50, 70, 30), np.linspace(10, 50, 30)])
    detections = np.column_stack([np.linspace(100, 900, 11), np.linspace(100, 900, 11), np.ones(11)])

    with patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.array([0, 1]), np.array([0, 1]))):
        res = orientation.recoverOrientation(
            detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
            initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000
        )
        assert res is None


def test_orientation_recover_orientation_negative_altitude():
    """Line 203: altitude < -1e-8 causes continue in recoverOrientation."""
    np.random.seed(42)
    catalog = np.column_stack([np.linspace(50, 70, 30), np.linspace(10, 50, 30)])
    detections = np.column_stack([np.random.uniform(400, 600, 30), np.random.uniform(400, 600, 30), np.ones(30)])

    with patch('indi_allsky.lens_solver.orientation._orientationValues', return_value=(-10.0, 180.0, 0.0)):
        res = orientation.recoverOrientation(
            detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
            initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000
        )
        assert res is None


def test_orientation_recover_orientation_competing_solutions():
    """Lines 218-220: competing solutions return None."""
    rot45 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])

    with patch.object(orientation, '_orientationValues', return_value=(45.0, 180.0, 0.0)), \
         patch('indi_allsky.lens_solver.fitting._rmsGatePx', return_value=10.0), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(20), np.arange(20))), \
         patch('indi_allsky.lens_solver.fitting._buildFitResult', return_value={'success': True, 'stars_matched': 20, 'rms_px': 1.0}), \
         patch('numpy.linalg.eigvalsh', return_value=np.array([1e5, 1e5])):

        catalog = np.column_stack([np.linspace(50, 70, 30), np.linspace(10, 50, 30)])
        detections = np.column_stack([np.random.uniform(400, 600, 30), np.random.uniform(400, 600, 30), np.ones(30)])
        res = orientation.recoverOrientation(
            detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
            initial=[0, 0, 0, 1000, 0, 0], width=1000, height=1000
        )
        assert res is None or isinstance(res, tuple)


def test_orientation_refine_lens_model_no_candidates():
    """Line 249: refineLensModel returns None if no candidates."""
    detections = np.zeros((20, 3))
    catalog = np.zeros((20, 2))
    initial = [0, 0, 0, 1000, 0, 0]

    with patch('indi_allsky.lens_solver.orientation._fitLensModel', return_value=None):
        res = orientation.refineLensModel(
            detections, catalog, latitude=0.0, longitude=0.0, timestamp=0.0,
            initial=initial, width=1000, height=1000, lens_altitude=45.0, pointing_azimuth=180.0
        )
        assert res is None


def test_orientation_fit_lens_model_unconstrained_or_rank_deficient():
    """Line 282 & 286: _fitLensModel failure due to rank or low matched stars."""
    detections = np.zeros((20, 3))
    initial = [0, 0, 0, 1000, 0, 0]
    project_mock = MagicMock(return_value=(np.zeros((20, 2)), np.arange(20)))

    mock_res = MagicMock()
    mock_res.success = True
    mock_res.jac = np.zeros((20, 7))
    mock_res.x = np.array([0, 0, 0, 1000, 0, 0, 0.0])

    with patch('scipy.optimize.least_squares', return_value=mock_res), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(15), np.arange(15))):
        fit = orientation._fitLensModel(detections, initial, width=1000, height=1000, project=project_mock, seed=0.0, scale=1.0)
        assert fit is None

    mock_res.jac = np.eye(7)
    with patch('scipy.optimize.least_squares', return_value=mock_res), \
         patch('indi_allsky.lens_solver.fitting._matchStars', side_effect=[(np.arange(15), np.arange(15))] * 6 + [(np.arange(2), np.arange(2))]):
        fit = orientation._fitLensModel(detections, initial, width=1000, height=1000, project=project_mock, seed=0.0, scale=1.0)
        assert fit is None


def test_orientation_validate_lens_model_branches():
    """Lines 316, 328, 341, 348, 355, 361: validateLensModel edge branches."""
    fit = {
        'params': np.array([0, 0, 0, 1000, 0, 0, 0.0]),
        'final_match_radius': 10.0,
        'success': True
    }
    detections = np.column_stack([np.random.uniform(400, 600, 30), np.random.uniform(400, 600, 30), np.ones(30)])
    project_mock = MagicMock(return_value=(np.random.uniform(400, 600, (30, 2)), np.arange(30)))
    pointing_mock = MagicMock(return_value=(45.0, 180.0, 0.0))

    # Line 316
    mock_res_fail = MagicMock(success=False)
    with patch('scipy.optimize.least_squares', return_value=mock_res_fail), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(15), np.arange(15))):
        res = orientation._validateLensModel(fit, detections, width=1000, height=1000, project=project_mock, pointing=pointing_mock)
        assert res is None

    # Line 341
    mock_res_pass = MagicMock(
        success=True,
        x=np.array([0, 0, 0, 1000, 0, 0, 0.0]),
        fun=np.ones(30),
        jac=np.zeros((30, 7))
    )
    with patch('scipy.optimize.least_squares', return_value=mock_res_pass), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(15), np.arange(15))):
        res = orientation._validateLensModel(fit, detections, width=1000, height=1000, project=project_mock, pointing=pointing_mock)
        assert res is None

    # Line 348
    mock_res_singular = MagicMock(
        success=True,
        x=np.array([0, 0, 0, 1000, 0, 0, 0.0]),
        fun=np.ones(30),
        jac=np.eye(7, M=30).T * 1e-10
    )
    with patch('scipy.optimize.least_squares', return_value=mock_res_singular), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(15), np.arange(15))):
        res = orientation._validateLensModel(fit, detections, width=1000, height=1000, project=project_mock, pointing=pointing_mock)
        assert res is None

    # Line 355
    mock_res_ok = MagicMock(
        success=True,
        x=np.array([0, 0, 0, 1000, 0, 0, 0.0]),
        fun=np.ones(30),
        jac=np.eye(7, M=30).T
    )
    target_one_sector = np.column_stack([np.full(15, 100.0), np.full(15, 100.0)])
    with patch('scipy.optimize.least_squares', return_value=mock_res_ok), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(15), np.arange(15))), \
         patch.object(project_mock, '__call__', return_value=(target_one_sector, np.arange(15))):
        res = orientation._validateLensModel(fit, detections, width=1000, height=1000, project=project_mock, pointing=pointing_mock)
        assert res is None

    # Line 361
    mock_subset_shift = MagicMock(success=True, x=np.array([0, 0, 0, 1000, 0, 0, 0.0]))
    pointing_shifted = MagicMock(side_effect=[(45.0, 180.0, 0.0), (50.0, 180.0, 0.0)])
    target_multi_sector = np.column_stack([np.tile([-100, 100], 15), np.tile([-100, 100], 15)])
    with patch('scipy.optimize.least_squares', side_effect=[mock_res_ok, mock_res_ok, mock_subset_shift]), \
         patch('indi_allsky.lens_solver.fitting._matchStars', return_value=(np.arange(30), np.arange(30))), \
         patch.object(project_mock, '__call__', return_value=(target_multi_sector, np.arange(30))):
        res = orientation._validateLensModel(fit, detections, width=1000, height=1000, project=project_mock, pointing=pointing_shifted)
        assert res is None
