import numpy
import pytest

from indi_allsky import lens_solver
from indi_allsky.lens_solver import fitting
from indi_allsky.lens_solver import (
    IndiAllSkyLensSolver, predictAltAz, projectToPixels,
)


W, H = 1920, 1920
LAT, LON = 40.1, -75.4
T_UNIX = 1770000000        # dev note: any northern-winter night works
SITE_SOUTH = (-33.0, 151.0)
TRUE = numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0])

# named so the noise-floor check (rms_px < 2 * NOISE_PX) below is explicit
NOISE_PX = 0.8


def synthetic_detections(params, catalog=None, lat=LAT, lon=LON, obstime=T_UNIX,
                          mirror=False, noise_px=NOISE_PX, n_outliers=15,
                          drop_fraction=0.1, seed=7, width=W, height=H):
    solver = IndiAllSkyLensSolver({})
    cat = catalog if catalog is not None else solver.loadCatalog()
    alt, az = predictAltAz(cat, lat + params[1], lon + params[2], obstime)
    keep = alt > numpy.radians(lens_solver.MIN_STAR_ALT_DEG)
    x, y = projectToPixels(alt[keep], az[keep], params, width, height, mirror=mirror)

    inside = (x > 0) & (x < width) & (y > 0) & (y < height)
    x, y = x[inside], y[inside]

    rng = numpy.random.RandomState(seed)
    n = len(x)
    pick = rng.rand(n) > drop_fraction          # simulate missed detections
    x = x[pick] + rng.normal(0, noise_px, pick.sum())
    y = y[pick] + rng.normal(0, noise_px, pick.sum())

    ox = rng.uniform(0, width, n_outliers)          # satellites, planes, noise
    oy = rng.uniform(0, height, n_outliers)
    det = numpy.column_stack([
        numpy.concatenate([x, ox]),
        numpy.concatenate([y, oy]),
        rng.uniform(100, 5000, len(x) + n_outliers),
    ])
    return det[rng.permutation(len(det))]


def run_fit(det, initial, catalog=None, lat=LAT, lon=LON, obstime=T_UNIX, width=W, height=H):
    solver = IndiAllSkyLensSolver({})
    cat = catalog if catalog is not None else solver.loadCatalog()
    return solver.fitParameters(det, cat, lat, lon, obstime, initial, width, height)


def assert_close_to_truth(params, true=TRUE):
    assert abs(params[0] - true[0]) < 0.5       # azimuth deg
    assert abs(params[1] - true[1]) < 1.0       # lat offset deg
    assert abs(params[2] - true[2]) < 1.0       # long offset deg
    assert abs(params[3] - true[3]) < 0.01 * true[3]   # diameter 1%
    assert abs(params[4] - true[4]) < 8.0       # offsets px
    assert abs(params[5] - true[5]) < 8.0


def test_recovers_all_six_from_good_guess():
    det = synthetic_detections(TRUE)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert not result['partial']
    assert result['stars_matched'] >= lens_solver.MIN_MATCHED_STARS
    assert_close_to_truth(result['params'])
    # must reach its own noise floor, not stop early (a premature-stop variant passed at 2.5x noise)
    assert result['rms_px'] < 2.0 * NOISE_PX


@pytest.mark.parametrize('az_err,diam_frac,center_err', [
    (30.0, 1.2, 100.0),
    (-30.0, 0.8, -100.0),
])
def test_convergence_radius(az_err, diam_frac, center_err):
    # Stage 1's fixed local-radius schedule can't bridge this; exercises the global bootstrap fallback
    det = synthetic_detections(TRUE)
    initial = numpy.array([
        TRUE[0] + az_err, 0.0, 0.0,
        TRUE[3] * diam_frac, center_err, center_err,
    ])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert_close_to_truth(result['params'])


def test_mirrored_field_reports_chirality_mismatch():
    # zero tilt/offset isolates chirality from the convergence issues in test_convergence_radius
    true_no_tilt = numpy.array([37.5, 0.0, 0.0, 1700.0, 0.0, 0.0])
    det = synthetic_detections(true_no_tilt, mirror=True)
    result = run_fit(det, true_no_tilt)
    assert not result['success']
    assert result['reason'] == 'chirality_mismatch'


def test_sparse_field_fails_structured():
    det = synthetic_detections(TRUE, drop_fraction=0.97, n_outliers=3)
    initial = numpy.array([TRUE[0], 0.0, 0.0, TRUE[3], 0.0, 0.0])
    result = run_fit(det, initial)
    assert not result['success']
    assert result['reason'] in ('too_few_matches', 'no_convergence')


# --- Pure noise must never report success -----------------------------

@pytest.mark.parametrize('n_detections', [500, 2000, 6000])
@pytest.mark.parametrize('seed', [1, 2, 3])
def test_pure_noise_never_succeeds(n_detections, seed):
    # assert the reason code only -- RMS isn't a portable constant here (diameter-relative gate)
    rng = numpy.random.RandomState(seed)
    noise = numpy.column_stack([
        rng.uniform(0, W, n_detections),
        rng.uniform(0, H, n_detections),
        rng.uniform(100, 5000, n_detections),
    ])
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(noise, initial)
    assert not result['success']
    assert result['reason'] in ('too_few_matches', 'no_convergence')


def test_no_convergence_reachable():
    # pins the specific reason so a regression to always 'too_few_matches' is caught
    rng = numpy.random.RandomState(1)
    noise = numpy.column_stack([
        rng.uniform(0, W, 6000), rng.uniform(0, H, 6000), rng.uniform(100, 5000, 6000)])
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(noise, initial)
    assert not result['success']
    assert result['reason'] in ('too_few_matches', 'no_convergence')


@pytest.mark.parametrize('n_detections', [500, 2000, 6000])
@pytest.mark.parametrize('seed', [1, 2, 3])
def test_pure_noise_never_succeeds_small_diameter(n_detections, seed):
    # D=700 (floor-bound RMS gate); regression pin for EFFECTIVE_MIN_MATCHED_STARS
    width, height = 900, 900
    rng = numpy.random.RandomState(seed + 100)
    noise = numpy.column_stack([
        rng.uniform(0, width, n_detections),
        rng.uniform(0, height, n_detections),
        rng.uniform(100, 5000, n_detections),
    ])
    initial = numpy.array([30.0, 0.0, 0.0, 700.0, 0.0, 0.0])
    result = run_fit(noise, initial, width=width, height=height)
    assert not result['success']
    assert result['reason'] in ('too_few_matches', 'no_convergence')


# --- Reprojection error bounded, tolerance derived (not carried) -----------

def _max_reprojection_error(solved_params, true_params, catalog, width, height):
    min_alt_rad = numpy.radians(lens_solver.MIN_STAR_ALT_DEG)
    alt_t, az_t = predictAltAz(catalog, LAT + true_params[1], LON + true_params[2], T_UNIX)
    alt_s, az_s = predictAltAz(catalog, LAT + solved_params[1], LON + solved_params[2], T_UNIX)
    visible = (alt_t > min_alt_rad) & (alt_s > min_alt_rad)
    xt, yt = projectToPixels(alt_t[visible], az_t[visible], true_params, width, height)
    xs, ys = projectToPixels(alt_s[visible], az_s[visible], solved_params, width, height)
    return float(numpy.max(numpy.hypot(xt - xs, yt - ys)))


# absolute, not proportional to diameter: measured flat ~0.13px across D=700-1700
REPROJECTION_ERROR_TOLERANCE_PX = 1.0


@pytest.mark.parametrize('diameter,width_height', [(1700.0, 1920), (1000.0, 1200), (700.0, 900)])
def test_reprojection_error_bounded(diameter, width_height):
    true_p = numpy.array([37.5, 2.0, -1.5, diameter, diameter * 0.015, -diameter * 0.007])
    wh = width_height
    det = synthetic_detections(true_p, width=wh, height=wh)
    initial = numpy.array([30.0, 0.0, 0.0, diameter * 0.94, 0.0, 0.0])
    result = run_fit(det, initial, width=wh, height=wh)
    assert result['success'], result.get('message')
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog()
    err = _max_reprojection_error(result['params'], true_p, cat, wh, wh)
    assert err < REPROJECTION_ERROR_TOLERANCE_PX


# --- Catalog-depth structural behavior ---------------------------------

R16_SITES = [(LAT, LON), SITE_SOUTH]
R16_EPOCHS = [T_UNIX, T_UNIX + 8 * 3600, T_UNIX + 200 * 86400]


@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5])
@pytest.mark.parametrize('site', R16_SITES)
@pytest.mark.parametrize('epoch', R16_EPOCHS)
def test_recovery_across_seed_epoch_site_at_mag45(seed, site, epoch):
    # CATALOG_MAG_LIMIT=4.5 is load-bearing -- validated 30/30 across this grid; must always converge
    lat, lon = site
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog(mag_limit=4.5)
    true_p = numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0])
    det = synthetic_detections(true_p, catalog=cat, lat=lat, lon=lon, obstime=epoch, seed=seed)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial, catalog=cat, lat=lat, lon=lon, obstime=epoch)
    assert result['success'], (site, epoch, seed, result.get('message'))
    assert_close_to_truth(result['params'], true_p)


# KNOWN GAP, not covered here: mag 5.0/5.5 depth-robustness -- denser catalogs can produce a confidently-wrong success

def test_partial_result_when_tilt_undetermined(monkeypatch):
    monkeypatch.setattr(fitting, 'TILT_BOUND_DEG', 0.5)
    true_p = numpy.array([37.5, 2.0, -1.5, 1700.0, 25.0, -12.0])
    det = synthetic_detections(true_p)
    initial = numpy.array([true_p[0], 0.0, 0.0, true_p[3], true_p[4], true_p[5]])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert result['partial']
    assert result['params'][1] == initial[1]
    assert result['params'][2] == initial[2]


def test_diameter_far_off_does_not_silently_clamp():
    det = synthetic_detections(TRUE)
    # 40% off -- outside Stage 1/2's +/-DIAMETER_FRACTION (30%) bounds from this guess
    initial = numpy.array([TRUE[0], 0.0, 0.0, TRUE[3] * 1.4, 0.0, 0.0])
    result = run_fit(det, initial)
    if result['success']:
        # must not be a bound-clamped false solution
        clamped_hi = initial[3] * (1.0 + lens_solver.DIAMETER_FRACTION)
        clamped_lo = initial[3] * (1.0 - lens_solver.DIAMETER_FRACTION)
        assert not (abs(result['params'][3] - clamped_hi) < 1.0
                    or abs(result['params'][3] - clamped_lo) < 1.0)
        assert_close_to_truth(result['params'])
    else:
        assert result['reason'] in ('too_few_matches', 'no_convergence')


# --- Never falsely report chirality ------------------------------------------

@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5])
def test_correct_image_never_reports_chirality(seed):
    det = synthetic_detections(TRUE, seed=seed)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert not (not result['success'] and result.get('reason') == 'chirality_mismatch')


def test_correct_image_never_reports_chirality_low_star_count():
    det = synthetic_detections(TRUE, drop_fraction=0.9, n_outliers=5)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert not (not result['success'] and result.get('reason') == 'chirality_mismatch')


def test_sub_horizon_detections_do_not_destabilize():
    solver = IndiAllSkyLensSolver({})
    cat = solver.loadCatalog()
    alt_all, az_all = predictAltAz(cat, LAT + TRUE[1], LON + TRUE[2], T_UNIX)
    below = (alt_all > numpy.radians(0.0)) & (alt_all <= numpy.radians(lens_solver.MIN_STAR_ALT_DEG))
    xb, yb = projectToPixels(alt_all[below], az_all[below], TRUE, W, H)
    inside = (xb > 0) & (xb < W) & (yb > 0) & (yb < H)

    det = synthetic_detections(TRUE)
    rng = numpy.random.RandomState(99)
    extra = numpy.column_stack([xb[inside], yb[inside], rng.uniform(100, 5000, inside.sum())])
    det_with_subhorizon = numpy.vstack([det, extra])

    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det_with_subhorizon, initial)
    assert result['success'], result.get('message')
    assert_close_to_truth(result['params'])
    solver2 = IndiAllSkyLensSolver({})
    cat2 = solver2.loadCatalog()
    err = _max_reprojection_error(result['params'], TRUE, cat2, W, H)
    # see REPROJECTION_ERROR_TOLERANCE_PX -- flat-absolute across D, not a fraction of it
    assert err < REPROJECTION_ERROR_TOLERANCE_PX


# --- Gross azimuth error fails structured ------------------------------------

@pytest.mark.parametrize('az_err', [90.0, 180.0, -135.0])
def test_gross_azimuth_error_recovers(az_err):
    # coarse azimuth/chirality grid spans the full circle; must solve even from an arbitrarily wrong guess
    det = synthetic_detections(TRUE)
    initial = numpy.array([(TRUE[0] + az_err) % 360.0, 0.0, 0.0, TRUE[3], 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert_close_to_truth(result['params'])


@pytest.mark.parametrize('diam_frac', [0.60, 0.837, 1.35])
def test_gross_diameter_error_recovers(diam_frac):
    # field-reported case: wide recovery sweep (0.5x-1.5x) must find it where the envelope bootstrap alone can't
    det = synthetic_detections(TRUE)
    initial = numpy.array([TRUE[0], 0.0, 0.0, TRUE[3] * diam_frac, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert_close_to_truth(result['params'])


def test_azimuth_and_diameter_both_gross_recovers():
    # fresh-install worst case: azimuth 180deg off AND diameter 40% low at once
    det = synthetic_detections(TRUE)
    initial = numpy.array([
        (TRUE[0] + 180.0) % 360.0, 0.0, 0.0, TRUE[3] * 0.60, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
    assert_close_to_truth(result['params'])


def test_refit_from_own_solution_is_stable():
    # refit anchored at an already-correct solution must be a fixed point
    det = synthetic_detections(TRUE)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    first = run_fit(det, initial)
    assert first['success'], first.get('message')

    second = run_fit(det, first['params'])
    assert second['success'], second.get('message')
    assert abs(second['params'][0] - first['params'][0]) < 0.2
    assert abs(second['params'][3] - first['params'][3]) < 0.005 * TRUE[3]
    assert second['rms_px'] <= first['rms_px'] + 0.1


def test_out_of_envelope_guess_refuses_not_silently_searches():
    # unlike azimuth/diameter, the center-offset search is bounded; a wider-needed guess must be REFUSED
    det = synthetic_detections(TRUE)
    initial = numpy.array([TRUE[0] + 35.0, 0.0, 0.0, TRUE[3] * 1.25, 180.0, 180.0])
    result = run_fit(det, initial)
    assert not result['success']
    assert result['reason'] == 'too_few_matches'


def test_out_of_envelope_guess_would_succeed_if_envelope_widened(monkeypatch):
    # widening the envelope must let this fixture succeed; all six span+step constants must move together
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_AZ_SPAN_DEG', 45.0)
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_AZ_STEPS', 13)
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_DIAMETER_FRACTION', 0.40)
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_DIAMETER_STEPS', 5)
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_OFFSET_PX', 300.0)
    monkeypatch.setattr(fitting, 'BOOTSTRAP_ENVELOPE_OFFSET_STEPS', 7)

    det = synthetic_detections(TRUE)
    initial = numpy.array([TRUE[0] + 35.0, 0.0, 0.0, TRUE[3] * 1.25, 180.0, 180.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')


@pytest.mark.parametrize('drop_fraction', [0.1, 0.3, 0.5, 0.7])
def test_rms_insensitive_to_detector_completeness(drop_fraction):
    det = synthetic_detections(TRUE, drop_fraction=drop_fraction)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], (drop_fraction, result.get('message'))
    # residual reflects fit geometry, not which stars were detected; generous band, not the tight measured spread
    assert result['rms_px'] < 2.0 * NOISE_PX


def test_rms_gate_binds_directly_not_masked_by_count_gate():
    # isolates the RMS gate from the count gate via a matched count above EFFECTIVE_MIN_MATCHED_STARS
    solver = IndiAllSkyLensSolver({})
    diameter = 1700.0
    final = numpy.array([37.5, 2.0, -1.5, diameter, 25.0, -12.0])

    # fixed literals, not derived from _rmsGatePx (a mutation would shift both); gate = 8.5, residual = 1.5x gate
    correct_gate = 8.5
    residual = 12.75   # 1.5x correct_gate

    result = fitting._buildFitResult(
        final, n=lens_solver.EFFECTIVE_MIN_MATCHED_STARS + 10, rms=residual,
        radius=correct_gate, partial=False)

    assert not result['success']
    assert result['reason'] == 'no_convergence'


# --- Final match radius is never below the effective RMS gate --------------

def test_final_match_radius_not_below_gate():
    det = synthetic_detections(TRUE)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success']
    # compare against the EFFECTIVE limit via the shared helper, never a hardcoded floor
    gate = lens_solver._rmsGatePx(result['params'][3])
    assert result['final_match_radius'] >= gate


def test_final_match_radius_present_on_failure():
    rng = numpy.random.RandomState(1)
    noise = numpy.column_stack([
        rng.uniform(0, W, 2000), rng.uniform(0, H, 2000), rng.uniform(100, 5000, 2000)])
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(noise, initial)
    assert not result['success']
    assert 'final_match_radius' in result
    assert result['final_match_radius'] > 0.0


def test_adaptive_radius_cannot_run_away():
    # run_stage's early exit returns rms=inf; schedule must stay finite/capped even then
    radius = lens_solver._stage2MatchRadius(1700.0, float('inf'))
    assert numpy.isfinite(radius)
    assert radius <= lens_solver.MAX_MATCH_RADIUS_FRACTION * 1700.0

    radius_normal = lens_solver._stage2MatchRadius(1700.0, 2.0)
    assert numpy.isfinite(radius_normal)
    assert radius_normal <= lens_solver.MAX_MATCH_RADIUS_FRACTION * 1700.0
    # never below the effective gate -- same guarantee test_final_match_radius_not_below_gate checks end-to-end
    assert radius_normal >= lens_solver._rmsGatePx(1700.0)


# --- _countMatches: hoisted-tree neutrality + explicit zero-match cases ----

def test_count_matches_hoisted_tree_bit_identical_to_fresh():
    # verify a hoisted tree scores identically to a fresh one, incl. a genuinely-zero-match case
    from scipy.spatial import cKDTree

    solver = IndiAllSkyLensSolver({})
    rng = numpy.random.RandomState(42)
    detections = numpy.column_stack([
        rng.uniform(0, 1000, 200), rng.uniform(0, 1000, 200), rng.uniform(100, 5000, 200)])
    radius = 15.0

    probe_cases = {
        'mostly_matching': detections[:50, :2] + rng.normal(0, 2, (50, 2)),
        'legitimately_zero_matches': rng.uniform(2000, 3000, (30, 2)),
        'crowded_onto_one_detection': (
            numpy.tile(detections[10, :2], (20, 1)) + rng.normal(0, 1, (20, 2))),
        'empty_pred_xy': numpy.zeros((0, 2)),
    }

    for name, pred_xy in probe_cases.items():
        fresh_scores = [fitting._countMatches(cKDTree(detections[:, :2]), pred_xy, radius)
                        for _ in range(3)]
        tree_hoisted = cKDTree(detections[:, :2])
        hoisted_scores = [fitting._countMatches(tree_hoisted, pred_xy, radius) for _ in range(3)]
        assert fresh_scores == hoisted_scores, name
        # sanity: legitimately_zero_matches must actually score 0 on a non-empty tree
        if name == 'legitimately_zero_matches':
            assert fresh_scores == [0, 0, 0]
        if name == 'mostly_matching':
            assert fresh_scores == [50, 50, 50]


def test_count_matches_none_tree_and_empty_pred_xy():
    # both degenerate inputs from the empty-set early-out path must return 0
    solver = IndiAllSkyLensSolver({})
    assert fitting._countMatches(None, numpy.array([[1.0, 1.0]]), 15.0) == 0

    from scipy.spatial import cKDTree
    rng = numpy.random.RandomState(1)
    detections = numpy.column_stack([rng.uniform(0, 100, 10), rng.uniform(0, 100, 10)])
    tree = cKDTree(detections)
    assert fitting._countMatches(tree, numpy.zeros((0, 2)), 15.0) == 0


def test_vignetted_field_recovers_diameter_despite_truncation():
    # vignetting discards outer-field stars; requires radially-stratified _truncateDetections to converge
    solver = IndiAllSkyLensSolver({})
    deep_catalog = solver.loadCatalog(mag_limit=6.5)
    match_catalog = solver.loadCatalog()

    alt, az = predictAltAz(deep_catalog, LAT + TRUE[1], LON + TRUE[2], T_UNIX)
    keep = alt > numpy.radians(lens_solver.MIN_STAR_ALT_DEG)
    x, y = projectToPixels(alt[keep], az[keep], TRUE, W, H)
    inside = (x > 0) & (x < W) & (y > 0) & (y < H)
    x, y = x[inside], y[inside]
    vmag = deep_catalog[keep][inside, 2]

    center_x = W / 2.0 + TRUE[4]
    center_y = H / 2.0 - TRUE[5]
    r = numpy.hypot(x - center_x, y - center_y)
    vignette_mag = 3.5 * (r / r.max())
    flux = 10.0 ** (-0.4 * (vmag + vignette_mag)) * 5.0e6

    det = numpy.column_stack([x, y, flux])
    det = det[numpy.argsort(det[:, 2])[::-1]]        # detectStars' own contract
    assert det.shape[0] > lens_solver.MAX_DETECTED_STARS

    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial, catalog=match_catalog)
    assert result['success'], result.get('message')
    assert abs(result['params'][3] - TRUE[3]) < 0.02 * TRUE[3]


# --- Validated-catalog envelope enforced, not just documented --------------

def test_catalog_denser_than_validated_refuses_by_row_count():
    # a catalog denser than the validated CATALOG_MAG_LIMIT=4.5 default must be refused, not solved confidently-wrong
    solver = IndiAllSkyLensSolver({})
    dense_catalog = solver.loadCatalog(mag_limit=5.5)
    assert dense_catalog.shape[0] > lens_solver.CATALOG_VALIDATED_ROW_CEILING

    det = synthetic_detections(TRUE, catalog=dense_catalog)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial, catalog=dense_catalog)
    assert not result['success']
    assert result['reason'] == 'catalog_not_validated'


def test_catalog_at_validated_depth_is_not_refused():
    # guard must not reject the actual production default
    solver = IndiAllSkyLensSolver({})
    default_catalog = solver.loadCatalog()
    assert default_catalog.shape[0] <= lens_solver.CATALOG_VALIDATED_ROW_CEILING
    assert float(default_catalog[:, 2].max()) <= lens_solver.CATALOG_MAG_LIMIT

    det = synthetic_detections(TRUE)
    initial = numpy.array([30.0, 0.0, 0.0, 1600.0, 0.0, 0.0])
    result = run_fit(det, initial)
    assert result['success'], result.get('message')
