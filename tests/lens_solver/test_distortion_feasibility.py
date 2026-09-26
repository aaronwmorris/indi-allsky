"""Numerical feasibility study, not a production calibration implementation.

Correspondences are supplied and synthetic centroids have no outliers. These
tests measure model capacity and coverage; they do not validate blind matching.
"""
import numpy as np
import pytest
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def cap(fov, count, seed):
    rng = np.random.default_rng(seed)
    theta = np.arccos(rng.uniform(np.cos(np.radians(fov / 2)), 1, count))
    phi = rng.uniform(-np.pi, np.pi, count)
    return np.column_stack((np.sin(theta)*np.cos(phi),
                            np.sin(theta)*np.sin(phi), np.cos(theta)))


def angles(rays):
    theta = np.arctan2(np.linalg.norm(rays[:, :2], axis=1), rays[:, 2])
    direction = rays[:, :2] / np.maximum(np.linalg.norm(rays[:, :2], axis=1)[:, None], 1e-15)
    return theta, direction


def curve(theta, family):
    return {
        'equisolid': lambda t: 2*np.sin(t/2),
        'equidistant': lambda t: t,
        'stereographic': lambda t: 2*np.tan(t/2),
        'orthographic': np.sin,
        'rectilinear': np.tan,
    }[family](theta)


def basis(theta, terms):
    q = np.sin(theta / 2) / np.sin(np.pi / 4)
    return q[:, None] ** np.arange(1, 2*terms + 2, 2)


def projection_study(family, fov, terms):
    # Independent ideal lens families; 1,000 px radius at the stated FOV edge.
    train, _ = angles(cap(fov, 1000, 3127))
    test, _ = angles(cap(fov, 10000, 3128))
    scale = 1000 / curve(np.radians(fov / 2), family)
    coeff = np.linalg.lstsq(basis(train, terms), scale*curve(train, family), rcond=None)[0]
    error = basis(test, terms) @ coeff - scale*curve(test, family)
    edge = test > np.radians(fov / 2)*0.9
    grid = np.linspace(0, np.radians(fov / 2), 1001)
    return dict(rms_px=float(np.sqrt(np.mean(error**2))),
                edge_max_px=float(np.max(np.abs(error[edge]))),
                monotonic=bool(np.all(np.diff(basis(grid, terms) @ coeff) > 0)))


def model(rays, params):
    # Fit pose, centre, scale and two radial terms together. Coordinates are
    # normalized by 1,000 px so optimizer conditioning is not set by units.
    theta, direction = angles(Rotation.from_rotvec(params[:3]).apply(rays))
    radius = basis(theta, 2) @ params[5:]
    return 1000 * (params[3:5] + radius[:, None]*direction)


TRUE_PARAMS = np.array([0., 0., 0., 0.05, -0.03, 1., 0.045, -0.012])


def coverage_study(layout, trials=12):
    rays = cap(180, 20000, 3116)
    xy = model(rays, TRUE_PARAMS)
    # Sensor rectangles clip the same optical mapping. The last two cases
    # simulate clouds/obstructions hiding calibration stars inside that sensor.
    bounds = {'circle': (1100, 1100), '4:3': (1000, 750),
              '16:9': (1000, 562.5), 'portrait': (562.5, 1000),
              'no_circle_edge': (650, 400), 'offset_crop': (600, 450)}
    bx, by = bounds.get(layout, (1100, 1100))
    shift = np.array([350, 100]) if layout == 'offset_crop' else np.zeros(2)
    visible = (np.abs(xy[:, 0]-shift[0]) < bx) & (np.abs(xy[:, 1]-shift[1]) < by)
    support = visible.copy()
    if layout == 'central_patch':
        support &= np.linalg.norm(xy - 1000*TRUE_PARAMS[3:5], axis=1) < 300
    elif layout == 'thin_strip':
        support &= np.abs(xy[:, 1]) < 30
    indices = np.flatnonzero(support)
    outcomes = []
    for seed in range(trials):
        rng = np.random.default_rng(seed)
        selected = rng.choice(indices, 100, replace=False)
        observed = xy[selected] + rng.normal(0, 0.7, (100, 2))
        # Deliberately favourable initialization isolates identifiability from
        # acquisition. Even these fits must not be extrapolated blindly.
        fit = least_squares(lambda p: (model(rays[selected], p)-observed).ravel(),
                            TRUE_PARAMS, max_nfev=200, x_scale='jac')
        holdout = visible.copy()
        holdout[selected] = False
        residual = model(rays[holdout], fit.x) - xy[holdout]
        training = model(rays[selected], fit.x) - observed
        grid = np.linspace(0, np.pi/2, 1001)
        outcomes.append((np.sqrt(np.mean(np.sum(training**2, axis=1))),
                         np.sqrt(np.mean(np.sum(residual**2, axis=1))),
                         np.all(np.diff(basis(grid, 2) @ fit.x[5:]) > 0),
                         fit.success))
    rows = np.asarray(outcomes)
    return dict(training_rms_px=float(np.median(rows[:, 0])),
                holdout_rms_px=float(np.median(rows[:, 1])),
                worst_holdout_rms_px=float(np.max(rows[:, 1])),
                nonmonotonic_trials=int(np.sum(rows[:, 2] == 0)),
                failed_trials=int(np.sum(rows[:, 3] == 0)))


def asymmetric_study():
    rays = cap(180, 5000, 3128)
    xy = model(rays, TRUE_PARAMS)
    u, v = (xy - 1000*TRUE_PARAMS[3:5]).T / 1000
    # Synthetic decentring, not a physical model of this user's dome.
    distorted = xy + 1000*np.column_stack((0.006*(3*u*u+v*v), 0.012*u*v))
    fit = least_squares(lambda p: (model(rays[:500], p)-distorted[:500]).ravel(),
                        TRUE_PARAMS, x_scale='jac')
    error = model(rays[500:], fit.x)-distorted[500:]
    return dict(holdout_rms_px=float(np.sqrt(np.mean(np.sum(error**2, axis=1)))),
                max_error_px=float(np.max(np.linalg.norm(error, axis=1))))


@pytest.mark.parametrize('family,fov', [('equisolid', 180), ('equidistant', 180),
    ('stereographic', 180), ('orthographic', 180), ('rectilinear', 90)])
def test_projection_comparison(family, fov):
    legacy = projection_study(family, fov, 0)
    corrected = projection_study(family, fov, 2)
    assert corrected['monotonic']
    assert corrected['rms_px'] <= legacy['rms_px'] + 1e-9
    if family == 'equisolid':
        assert corrected['edge_max_px'] < 1e-9


@pytest.mark.parametrize('layout', ['circle', '4:3', '16:9', 'portrait',
                                   'no_circle_edge', 'offset_crop'])
def test_cropped_calibration_predicts_unseen_stars(layout):
    result = coverage_study(layout)
    assert result['failed_trials'] == 0
    assert result['worst_holdout_rms_px'] < 0.7


def test_central_matches_do_not_validate_edge_extrapolation():
    result = coverage_study('central_patch')
    assert result['training_rms_px'] < 1.1
    assert result['holdout_rms_px'] > 10


def test_two_terms_are_not_a_universal_projection_model():
    result = projection_study('rectilinear', 160, 2)
    assert result['rms_px'] > 20
    assert result['edge_max_px'] > 100
    assert not projection_study('rectilinear', 160, 1)['monotonic']


def test_radial_fit_leaves_asymmetric_residuals():
    assert asymmetric_study()['holdout_rms_px'] > 4
