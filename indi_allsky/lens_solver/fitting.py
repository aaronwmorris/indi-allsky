import collections
import time

import numpy
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from .projection import predictAltAz
from .projection import projectToPixels


MIN_MATCHED_STARS = 20
MAX_RMS_FRACTION = 0.005      # of solved image circle diameter
# below this the RMS gate cannot distinguish good fits from bad; refuse
MIN_VIABLE_DIAMETER_PX = 700
TILT_BOUND_DEG = 20.0
DIAMETER_FRACTION = 0.30      # +/- of initial guess
# diameter leverage lives at large radius (~r^2); raising this cut quietly
# destroys the fit's ability to constrain diameter -- re-measure before changing
MIN_STAR_ALT_DEG = 10.0

# degrees-of-freedom margin for least_squares, not a tuned constant
MIN_FIT_PAIR_MARGIN = 2

# least_squares stalls on a start sitting exactly on a bound; clip inside
FEASIBILITY_EPSILON_FRACTION = 1e-9
FEASIBILITY_EPSILON_MIN = 1e-9

# coarse azimuth/chirality grid spans the full circle -- an azimuth guess
# can be arbitrarily wrong and azimuth-only probes are cheap
COARSE_GRID_HALF_SPAN_DEG = 180.0
COARSE_GRID_STEP_DEG = 7.5
COARSE_MATCH_RADIUS_FRACTION = 0.02
MIN_COARSE_MATCH_RADIUS_PX = 8.0
# never recommend a destructive image flip off a handful of noise matches
CHIRALITY_MIN_RATIO = 1.5

STAGE1_AZIMUTH_BOUND_DEG = 60.0
STAGE1_MATCH_RADIUS_FRACTIONS = (0.02, 0.008)   # two match->fit rounds
STAGE2_AZIMUTH_BOUND_DEG = 30.0

# shared radius for the stage1-vs-stage2 comparison only; reported scores
# come from each stage's own native radius
COMMON_SCORE_RADIUS_FRACTION = 0.004
MIN_COMMON_SCORE_RADIUS_PX = 6.0
TILT_BOUND_MARGIN_DEG = 0.5

# RMS-adaptive Stage-2 match radius (see _stage2MatchRadius)
RADIUS_RMS_FACTOR = 3.0
MAX_MATCH_RADIUS_FRACTION = 0.06
MIN_STAGE2_MATCH_RADIUS_PX = 6.0
MAX_FIT_ROUNDS = 8
CONVERGENCE_RMS_EPS_PX = 0.01

FIT_LOSS = 'soft_l1'
# f_scale tracks the current match radius; a fixed value treats every pair
# as an outlier at large starting residuals and the fit stops early
F_SCALE_RADIUS_FACTOR = 1.0

# RMS acceptance gate floor, derived at the binding case D=700
RMS_GATE_FLOOR_PX = 5.0

# cap detections before matching -- see _truncateDetections
MAX_DETECTED_STARS = 500
DETECTED_STARS_RADIAL_BINS = 8

# fit offset bounds: +/- this fraction of the anchor diameter
OFFSET_BOUND_FRACTION = 0.25

# global bootstrap fallback: coarse-then-zoom grid over (azimuth, diameter,
# offset) used only to SEED a fresh staged fit after the cheap path fails --
# it never feeds a result directly, so the normal gates still apply.
# Spans are bounded to az +/-30deg, D +/-20%, center +/-100px; an unbounded
# grid measured 78-138s on a Pi 4 and wider stage radii were measured to
# converge confidently to wrong local optima.
BOOTSTRAP_MIN_MATCH_FRACTION = 0.75   # of MIN_MATCHED_STARS to trust a seed
MIN_SEED_MATCH_COUNT = max(1, int(BOOTSTRAP_MIN_MATCH_FRACTION * MIN_MATCHED_STARS))
BOOTSTRAP_ZOOM_AZ_STEPS = 7
BOOTSTRAP_ZOOM_DIAMETER_FRACTION = DIAMETER_FRACTION / 3.0
BOOTSTRAP_ZOOM_OFFSET_FRACTION = OFFSET_BOUND_FRACTION / 4.0
BOOTSTRAP_ZOOM_DIAMETER_STEPS = 3
BOOTSTRAP_ZOOM_OFFSET_STEPS = 3
BOOTSTRAP_ENVELOPE_AZ_SPAN_DEG = 30.0
BOOTSTRAP_ENVELOPE_AZ_STEPS = int(round(2 * BOOTSTRAP_ENVELOPE_AZ_SPAN_DEG / COARSE_GRID_STEP_DEG)) + 1
BOOTSTRAP_ENVELOPE_DIAMETER_FRACTION = 0.20
BOOTSTRAP_ENVELOPE_DIAMETER_STEPS = 3
BOOTSTRAP_ENVELOPE_OFFSET_PX = 100.0
BOOTSTRAP_ENVELOPE_OFFSET_STEPS = 3

# wide recovery sweep: last-resort seed search after the bootstrap also
# fails -- full-circle azimuth jointly with a geometric 0.6x-1.7x diameter
# schedule (offsets stay at the entered values). Diameters below
# MIN_VIABLE_DIAMETER_PX are dropped: without that clamp, pure-noise
# fields at D=700 found sub-floor "solutions" that passed every gate.
RECOVERY_AZ_STEP_DEG = 15.0
RECOVERY_AZ_STEPS = int(round(360.0 / RECOVERY_AZ_STEP_DEG))
RECOVERY_AZ_SPAN_DEG = 180.0 - RECOVERY_AZ_STEP_DEG / 2.0
RECOVERY_DIAMETER_MIN_MULT = 0.6
RECOVERY_DIAMETER_MAX_MULT = 1.7
RECOVERY_DIAMETER_STEPS = 11

# refinement restarts: re-run the fit anchored at its own solution until
# RMS stops improving (bounds/radii/scale anchor to the initial guess, so
# a far start otherwise converges slightly short of the optimum)
REFINE_MAX_RESTARTS = 3
REFINE_MIN_RMS_IMPROVEMENT_PX = 0.05

# soft_l1 can fit small pure-noise subsets within the RMS gate (measured
# false successes at 20-33 matches); require double MIN_MATCHED_STARS --
# genuine fits clear this by an order of magnitude
MATCH_CONFIDENCE_MULTIPLIER = 2.0
EFFECTIVE_MIN_MATCHED_STARS = int(round(MATCH_CONFIDENCE_MULTIPLIER * MIN_MATCHED_STARS))


# per-solve invariants, built once by the solver and shared by every
# fit-pipeline method via FitEngine.ctx
SolveContext = collections.namedtuple('SolveContext', [
    'detections', 'tree', 'catalog', 'latitude', 'longitude',
    'obstime_unix', 'image_width', 'image_height', 'min_alt_rad',
    'initial_params',
])


def _rmsGatePx(diameter):
    # RMS acceptance gate: shared by the pass/fail check, the Stage-2
    # radius floor (a scoring radius below the gate could never fail it),
    # and quality reporting, so the three cannot drift apart
    return max(MAX_RMS_FRACTION * diameter, RMS_GATE_FLOOR_PX)


def _coarseRadiusPx(diameter):
    return max(MIN_COARSE_MATCH_RADIUS_PX, COARSE_MATCH_RADIUS_FRACTION * diameter)


def _stage2MatchRadius(diameter, rms_prev):
    # match radius tracks the previous round's RMS (a fixed small radius
    # admits only inner-field stars with no diameter/tilt leverage);
    # floored at the RMS gate, capped so rms_prev=inf cannot match everything
    floor = max(MIN_STAGE2_MATCH_RADIUS_PX, _rmsGatePx(diameter))
    if not numpy.isfinite(rms_prev):
        return floor
    return min(MAX_MATCH_RADIUS_FRACTION * diameter, max(floor, RADIUS_RMS_FACTOR * rms_prev))


def _feasibleStart(x0, lower, upper):
    # clip strictly inside the bounds
    lower = numpy.asarray(lower, dtype=numpy.float64)
    upper = numpy.asarray(upper, dtype=numpy.float64)
    span = numpy.maximum(upper - lower, FEASIBILITY_EPSILON_MIN)
    eps = numpy.maximum(span * FEASIBILITY_EPSILON_FRACTION, FEASIBILITY_EPSILON_MIN)
    return numpy.clip(numpy.asarray(x0, dtype=numpy.float64), lower + eps, upper - eps)


def _truncateDetections(detections, center_x, center_y, max_count):
    # cap detections per radial annulus, not brightest-N overall: fisheyes
    # vignette 1-2 mag at the edge, and the outer field is exactly the
    # diameter-leverage population that flux ranking would discard
    if detections.shape[0] <= max_count:
        return detections

    r = numpy.hypot(detections[:, 0] - center_x, detections[:, 1] - center_y)
    max_r = float(r.max())
    if max_r <= 0.0:
        max_r = 1.0
    bin_idx = numpy.minimum(
        (r / max_r * DETECTED_STARS_RADIAL_BINS).astype(int),
        DETECTED_STARS_RADIAL_BINS - 1)

    per_bin = max(1, max_count // DETECTED_STARS_RADIAL_BINS)
    bin_lists = [numpy.flatnonzero(bin_idx == b) for b in range(DETECTED_STARS_RADIAL_BINS)]
    taken = [min(per_bin, len(lst)) for lst in bin_lists]

    # top up leftover slots round-robin, not by global brightness -- a
    # global pass would rebuild brightest-N for the crowded inner bins
    total = sum(taken)
    b = 0
    while total < max_count:
        if taken[b] < len(bin_lists[b]):
            taken[b] += 1
            total += 1
        b = (b + 1) % DETECTED_STARS_RADIAL_BINS
        if b == 0 and all(taken[i] >= len(bin_lists[i]) for i in range(DETECTED_STARS_RADIAL_BINS)):
            break   # every bin exhausted -- fewer than max_count candidates in total

    keep_parts = [bin_lists[b][:taken[b]] for b in range(DETECTED_STARS_RADIAL_BINS)]
    keep_idx = numpy.concatenate(keep_parts) if keep_parts else numpy.array([], dtype=int)

    truncated = detections[numpy.sort(keep_idx)]
    return truncated[numpy.argsort(truncated[:, 2])[::-1]]


def _matchStars(detections, pred_xy, radius):
    # greedy unique nearest-neighbor, closest pairs first; pairs are
    # frozen per round (least_squares needs a constant residual length)
    if len(detections) == 0 or len(pred_xy) == 0:
        return numpy.zeros((0,), dtype=int), numpy.zeros((0,), dtype=int)

    tree = cKDTree(detections[:, :2])
    dist, det_idx = tree.query(pred_xy, k=1, distance_upper_bound=radius)

    order = numpy.argsort(dist)
    used_det, pred_m, det_m = set(), [], []
    for p in order:
        if not numpy.isfinite(dist[p]):
            break
        d = det_idx[p]
        if d in used_det:
            continue
        used_det.add(d)
        pred_m.append(p)
        det_m.append(d)

    return numpy.array(pred_m, dtype=int), numpy.array(det_m, dtype=int)


def _countMatches(tree, pred_xy, radius):
    # vectorized match count for grid scoring only (never feeds a fit;
    # _matchStars provides the one-to-one pairing for that). `tree` is
    # prebuilt by the caller once per solve.
    if tree is None or len(pred_xy) == 0:
        return 0

    dist, det_idx = tree.query(pred_xy, k=1, distance_upper_bound=radius)
    finite = numpy.isfinite(dist)
    # count UNIQUE detections -- a per-prediction isfinite().sum() lets
    # a wrong parameter set inflate its score by crowding predictions
    # onto few detections (measured: picked the wrong azimuth)
    return int(numpy.unique(det_idx[finite]).shape[0])


def _chiralityMismatchResult(best_mirror_count, coarse_radius):
    return {
        'success': False,
        'reason': 'chirality_mismatch',
        'message': ('Image appears mirrored relative to the expected '
                    'orientation. Toggle exactly one of Config -> Image -> '
                    'Flip Image Horizontally or Flip Image Vertically, '
                    'then re-solve.'),
        'stars_matched': best_mirror_count,
        'final_match_radius': coarse_radius,
    }


def _buildFitResult(final, n, rms, radius, partial):
    if n < EFFECTIVE_MIN_MATCHED_STARS:
        return {
            'success': False,
            'reason': 'too_few_matches',
            'message': 'Only {0:d} stars matched the catalog (need {1:d}). '
                       'Sky may be cloudy, moonlit, or the current values '
                       'too far off.'.format(n, EFFECTIVE_MIN_MATCHED_STARS),
            'stars_matched': n,
            'rms_px': rms,
            'final_match_radius': radius,
        }

    if rms > _rmsGatePx(final[3]):
        return {
            'success': False,
            'reason': 'no_convergence',
            'message': 'Could not get a precise fit (residual {0:0.1f} px). '
                       'Solve recovers any azimuth and diameters off by up '
                       'to roughly {1:d}%, but the X/Y offsets must be within '
                       'about {2:d} px of correct -- check those fields, or '
                       'the sky may be too poor to solve.'.format(
                           rms,
                           int(round((1.0 - RECOVERY_DIAMETER_MIN_MULT) * 100)),
                           int(BOOTSTRAP_ENVELOPE_OFFSET_PX)),
            'stars_matched': n,
            'rms_px': rms,
            'final_match_radius': radius,
        }

    final = final.copy()
    final[0] = final[0] % 360.0
    return {
        'success': True,
        'params': final,
        'mirror_detected': False,
        'partial': partial,
        'stars_matched': n,
        'rms_px': rms,
        'final_match_radius': radius,
    }


class FitEngine(object):
    """One staged fit over a fixed SolveContext: coarse azimuth/chirality
    grid, two least-squares stages, seed-search fallbacks, and refinement
    restarts. Counters are exposed for the solver's timing dict.
    """

    def __init__(self, ctx):
        self.ctx = ctx

        self.residual_evals = 0
        self.predict_calls = 0
        self.coarse_s = 0.0
        self.fit_s = 0.0

    def fitWithFallbacks(self, p0, diameter0):
        result = self._runFitFrom(p0, diameter0)
        if result['success']:
            return self._refineResult(result)

        if result['reason'] not in ('too_few_matches', 'no_convergence'):
            return result

        # seed searches, cheapest first; each seed re-enters the staged fit
        # (recovery re-anchors at the seed's diameter -- anchoring at the
        # entered value would exclude the answer the sweep found). The
        # original failure is kept if no seed produces a passing fit.
        for search, anchor_at_seed in ((self._globalBootstrapSearch, False),
                                       (self._wideRecoverySearch, True)):
            _t0 = time.monotonic()
            seed = search(p0, diameter0)
            self.coarse_s += time.monotonic() - _t0
            if seed is None:
                continue

            retry = self._runFitFrom(seed, seed[3] if anchor_at_seed else diameter0)
            if retry['success']:
                return self._refineResult(retry)

        return result

    def _matchAtParams(self, params, radius, precomputed_alt_az=None):
        ctx = self.ctx
        if precomputed_alt_az is not None:
            alt, az = precomputed_alt_az
        else:
            alt, az = predictAltAz(ctx.catalog, ctx.latitude + params[1],
                                   ctx.longitude + params[2], ctx.obstime_unix)
            self.predict_calls += 1

        visible = numpy.flatnonzero(alt > ctx.min_alt_rad)
        x, y = projectToPixels(alt[visible], az[visible], params,
                               ctx.image_width, ctx.image_height)
        self.predict_calls += 1
        pred_m, det_m = _matchStars(ctx.detections, numpy.column_stack([x, y]), radius)
        return visible[pred_m], det_m

    def _scoreAtParams(self, params, radius):
        ctx = self.ctx
        cat_idx, det_idx = self._matchAtParams(params, radius)
        if len(cat_idx) == 0:
            return 0, float('inf')

        alt, az = predictAltAz(ctx.catalog[cat_idx], ctx.latitude + params[1],
                               ctx.longitude + params[2], ctx.obstime_unix)
        self.predict_calls += 1
        x, y = projectToPixels(alt, az, params, ctx.image_width, ctx.image_height)
        self.predict_calls += 1
        resid = numpy.column_stack([x, y]) - ctx.detections[det_idx, :2]
        rms = float(numpy.sqrt(numpy.mean(numpy.sum(resid ** 2, axis=1))))
        return len(cat_idx), rms

    def _fitStage(self, params, free_idx, lower, upper, radius, precomputed_alt_az=None):
        ctx = self.ctx
        cat_idx, det_idx = self._matchAtParams(
            params, radius, precomputed_alt_az=precomputed_alt_az)

        if len(cat_idx) < len(free_idx) + MIN_FIT_PAIR_MARGIN:
            return params, 0, float('inf')

        cat_sub = ctx.catalog[cat_idx]
        target_xy = ctx.detections[det_idx, :2]
        tilt_free = 1 in free_idx or 2 in free_idx

        fixed_alt_az = None
        if not tilt_free:
            # tilt frozen -> alt/az constant across residual evaluations
            fixed_alt_az = predictAltAz(
                cat_sub, ctx.latitude + params[1], ctx.longitude + params[2],
                ctx.obstime_unix)
            self.predict_calls += 1

        def residuals(free_values):
            self.residual_evals += 1
            trial = params.copy()
            trial[free_idx] = free_values
            if fixed_alt_az is None:
                alt, az = predictAltAz(
                    cat_sub, ctx.latitude + trial[1], ctx.longitude + trial[2],
                    ctx.obstime_unix)
                # counted only here so the counter catches a frozen-tilt regression
                self.predict_calls += 1
            else:
                alt, az = fixed_alt_az
            x, y = projectToPixels(alt, az, trial, ctx.image_width, ctx.image_height)
            return numpy.column_stack([x, y]).ravel() - target_xy.ravel()

        x0 = _feasibleStart(params[free_idx], lower, upper)
        res = least_squares(
            residuals, x0, bounds=(lower, upper),
            loss=FIT_LOSS, f_scale=radius * F_SCALE_RADIUS_FACTOR)

        out = params.copy()
        out[free_idx] = res.x
        n, rms = self._scoreAtParams(out, radius)
        return out, n, rms

    def _coarseAzimuthSearch(self, p0, radius):
        ctx = self.ctx
        # alt/az depends only on the lat/long offset, fixed for the whole
        # grid -- predict once, project many times
        alt, az = predictAltAz(ctx.catalog, ctx.latitude + p0[1],
                               ctx.longitude + p0[2], ctx.obstime_unix)
        self.predict_calls += 1
        visible = numpy.flatnonzero(alt > ctx.min_alt_rad)
        alt_v, az_v = alt[visible], az[visible]

        best = {'count': -1, 'az': float(p0[0])}
        best_mirror_count = -1

        if len(alt_v) == 0:
            return best, best_mirror_count, alt, az

        grid = numpy.arange(
            -COARSE_GRID_HALF_SPAN_DEG,
            COARSE_GRID_HALF_SPAN_DEG + COARSE_GRID_STEP_DEG / 2.0,
            COARSE_GRID_STEP_DEG)
        for d_az in grid:
            trial = p0.copy()
            trial[0] = p0[0] + d_az
            for mirror in (False, True):
                x, y = projectToPixels(alt_v, az_v, trial, ctx.image_width,
                                       ctx.image_height, mirror=mirror)
                self.predict_calls += 1
                count = _countMatches(ctx.tree, numpy.column_stack([x, y]), radius)
                if mirror:
                    best_mirror_count = max(best_mirror_count, count)
                elif count > best['count']:
                    best = {'count': count, 'az': float(trial[0])}

        # full-catalog (alt, az) returned so Stage 1 can reuse it
        return best, best_mirror_count, alt, az

    def _gridSearchCandidate(self, p0, diameter0, radius, az_span, az_steps,
                              diameter_values, offset_span_fraction, offset_steps):
        # one pass of a seed grid over (azimuth, diameter, offsets), scored
        # by raw match count; tilt stays at p0's value. Score against the
        # FULL catalog -- brightest-N-only scoring was tried and picked
        # wrong azimuths.
        ctx = self.ctx
        alt, az = predictAltAz(
            ctx.catalog, ctx.latitude + p0[1], ctx.longitude + p0[2], ctx.obstime_unix)
        self.predict_calls += 1
        visible = numpy.flatnonzero(alt > ctx.min_alt_rad)
        alt_v, az_v = alt[visible], az[visible]

        best = None

        if len(alt_v) == 0:
            return best

        az_values = (numpy.array([0.0]) if az_steps <= 1 else
                     numpy.linspace(-az_span, az_span, az_steps))
        off_values = numpy.linspace(-offset_span_fraction, offset_span_fraction, offset_steps)

        for d_az in az_values:
            for diameter in diameter_values:
                trial0 = p0.copy()
                trial0[0] = p0[0] + d_az
                trial0[3] = diameter
                for fx in off_values:
                    for fy in off_values:
                        trial = trial0.copy()
                        trial[4] = p0[4] + fx * diameter0
                        trial[5] = p0[5] + fy * diameter0
                        x, y = projectToPixels(alt_v, az_v, trial,
                                               ctx.image_width, ctx.image_height)
                        self.predict_calls += 1
                        count = _countMatches(
                            ctx.tree, numpy.column_stack([x, y]), radius)
                        if count < MIN_SEED_MATCH_COUNT:
                            continue
                        if best is None or count > best[0]:
                            best = (count, trial.copy())
        return best

    def _globalBootstrapSearch(self, p0, diameter0):
        # envelope-bounded coarse pass, then a zoom pass around the winner
        radius = _coarseRadiusPx(diameter0)

        coarse_diameters = diameter0 * numpy.linspace(
            1.0 - BOOTSTRAP_ENVELOPE_DIAMETER_FRACTION,
            1.0 + BOOTSTRAP_ENVELOPE_DIAMETER_FRACTION,
            BOOTSTRAP_ENVELOPE_DIAMETER_STEPS)
        coarse = self._gridSearchCandidate(
            p0, diameter0, radius,
            BOOTSTRAP_ENVELOPE_AZ_SPAN_DEG, BOOTSTRAP_ENVELOPE_AZ_STEPS,
            coarse_diameters,
            BOOTSTRAP_ENVELOPE_OFFSET_PX / diameter0, BOOTSTRAP_ENVELOPE_OFFSET_STEPS)
        if coarse is None:
            return None

        zoom_diameters = diameter0 * numpy.linspace(
            1.0 - BOOTSTRAP_ZOOM_DIAMETER_FRACTION,
            1.0 + BOOTSTRAP_ZOOM_DIAMETER_FRACTION,
            BOOTSTRAP_ZOOM_DIAMETER_STEPS)
        zoom = self._gridSearchCandidate(
            coarse[1], diameter0, radius,
            COARSE_GRID_STEP_DEG, BOOTSTRAP_ZOOM_AZ_STEPS,
            zoom_diameters,
            BOOTSTRAP_ZOOM_OFFSET_FRACTION, BOOTSTRAP_ZOOM_OFFSET_STEPS)

        if zoom is not None and zoom[0] > coarse[0]:
            return zoom[1]
        return coarse[1]

    def _wideRecoverySearch(self, p0, diameter0):
        # last-resort seed search (see RECOVERY_*): full-circle azimuth x
        # geometric diameter schedule; zoom re-anchors at the winner's diameter
        diameter_values = diameter0 * numpy.geomspace(
            RECOVERY_DIAMETER_MIN_MULT, RECOVERY_DIAMETER_MAX_MULT,
            RECOVERY_DIAMETER_STEPS)
        diameter_values = diameter_values[diameter_values >= MIN_VIABLE_DIAMETER_PX]
        if len(diameter_values) == 0:
            return None

        coarse = self._gridSearchCandidate(
            p0, diameter0, _coarseRadiusPx(diameter0),
            RECOVERY_AZ_SPAN_DEG, RECOVERY_AZ_STEPS,
            diameter_values, 0.0, 1)
        if coarse is None:
            return None

        seed_diameter = coarse[1][3]
        zoom_diameters = seed_diameter * numpy.linspace(
            1.0 - BOOTSTRAP_ZOOM_DIAMETER_FRACTION, 1.0 + BOOTSTRAP_ZOOM_DIAMETER_FRACTION,
            BOOTSTRAP_ZOOM_DIAMETER_STEPS)
        zoom_diameters = zoom_diameters[zoom_diameters >= MIN_VIABLE_DIAMETER_PX]
        zoom = None
        if len(zoom_diameters):
            zoom = self._gridSearchCandidate(
                coarse[1], seed_diameter, _coarseRadiusPx(seed_diameter),
                COARSE_GRID_STEP_DEG, BOOTSTRAP_ZOOM_AZ_STEPS,
                zoom_diameters,
                BOOTSTRAP_ZOOM_OFFSET_FRACTION, BOOTSTRAP_ZOOM_OFFSET_STEPS)

        if zoom is not None and zoom[0] > coarse[0]:
            return zoom[1]
        return coarse[1]

    def _runStage1(self, p, diameter0, precomputed_alt_az):
        idx1 = numpy.array([0, 3, 4, 5])
        offset_bound = diameter0 * OFFSET_BOUND_FRACTION
        lo1 = [p[0] - STAGE1_AZIMUTH_BOUND_DEG,
               diameter0 * (1.0 - DIAMETER_FRACTION),
               -offset_bound, -offset_bound]
        hi1 = [p[0] + STAGE1_AZIMUTH_BOUND_DEG,
               diameter0 * (1.0 + DIAMETER_FRACTION),
               offset_bound, offset_bound]

        n, rms, radius = 0, float('inf'), MIN_COARSE_MATCH_RADIUS_PX
        for fraction in STAGE1_MATCH_RADIUS_FRACTIONS:
            radius = max(MIN_COARSE_MATCH_RADIUS_PX, fraction * diameter0)
            p, n, rms = self._fitStage(
                p, idx1, lo1, hi1, radius, precomputed_alt_az=precomputed_alt_az)

        return p, n, rms, radius

    def _runStage2(self, p, diameter0, rms_seed):
        idx2 = numpy.arange(6)
        offset_bound = diameter0 * OFFSET_BOUND_FRACTION
        lo2 = [p[0] - STAGE2_AZIMUTH_BOUND_DEG, -TILT_BOUND_DEG, -TILT_BOUND_DEG,
               diameter0 * (1.0 - DIAMETER_FRACTION), -offset_bound, -offset_bound]
        hi2 = [p[0] + STAGE2_AZIMUTH_BOUND_DEG, TILT_BOUND_DEG, TILT_BOUND_DEG,
               diameter0 * (1.0 + DIAMETER_FRACTION), offset_bound, offset_bound]

        rms_prev = rms_seed
        n, rms, radius = 0, float('inf'), MIN_STAGE2_MATCH_RADIUS_PX
        prev_n, prev_rms = None, None
        for _round in range(MAX_FIT_ROUNDS):
            radius = _stage2MatchRadius(p[3], rms_prev)
            p, n, rms = self._fitStage(p, idx2, lo2, hi2, radius)

            rms_prev = rms if numpy.isfinite(rms) else rms_prev
            converged = (prev_rms is not None and prev_n == n
                         and abs(rms - prev_rms) < CONVERGENCE_RMS_EPS_PX)
            prev_n, prev_rms = n, rms
            if converged:
                break

        return p, n, rms, radius

    def _choosePartialOrFull(self, p1, p2, diameter0):
        # same-radius comparison used only for this decision
        common_radius = max(MIN_COMMON_SCORE_RADIUS_PX, COMMON_SCORE_RADIUS_FRACTION * diameter0)
        n1_common, rms1_common = self._scoreAtParams(p1, common_radius)
        n2_common, rms2_common = self._scoreAtParams(p2, common_radius)

        tilt_on_bound = (TILT_BOUND_DEG - abs(p2[1]) < TILT_BOUND_MARGIN_DEG
                          or TILT_BOUND_DEG - abs(p2[2]) < TILT_BOUND_MARGIN_DEG)

        if rms2_common > rms1_common or tilt_on_bound:
            # Stage 2 didn't improve or tilt hit its bound -- never fabricate a tilt
            winner = p1.copy()
            winner[1] = self.ctx.initial_params[1]
            winner[2] = self.ctx.initial_params[2]
            n_common, partial = n1_common, True
        else:
            winner, n_common, partial = p2, n2_common, False

        # cross-scale consistency: require the fit to hold up at BOTH the
        # common and gate radii -- coincidental noise alignments rarely
        # survive two scales, genuine ~1px fits are unaffected
        gate_radius = _rmsGatePx(winner[3])
        n_gate, rms_gate = self._scoreAtParams(winner, gate_radius)

        n = min(n_gate, n_common)
        return winner, n, rms_gate, gate_radius, partial

    def _runFitFrom(self, p0, diameter0, skip_coarse=False):
        # coarse azimuth/chirality grid -> Stage 1 -> Stage 2 ->
        # partial-vs-full decision -> gated result. skip_coarse starts at
        # p0's azimuth directly -- for refinement restarts, where azimuth
        # is already known and the full-circle grid is pure waste.
        ctx = self.ctx
        coarse_radius = _coarseRadiusPx(diameter0)

        _t0 = time.monotonic()
        if skip_coarse:
            alt0, az0 = predictAltAz(ctx.catalog, ctx.latitude + p0[1],
                                     ctx.longitude + p0[2], ctx.obstime_unix)
            self.predict_calls += 1
            best = {'count': 0, 'az': float(p0[0])}
            best_mirror_count = -1
        else:
            best, best_mirror_count, alt0, az0 = self._coarseAzimuthSearch(p0, coarse_radius)
        self.coarse_s += time.monotonic() - _t0

        if (best_mirror_count >= MIN_MATCHED_STARS
                and best_mirror_count > CHIRALITY_MIN_RATIO * max(best['count'], 1)):
            return _chiralityMismatchResult(best_mirror_count, coarse_radius)

        _t0 = time.monotonic()
        p = p0.copy()
        p[0] = best['az']

        p1, _n1, rms1, _radius1 = self._runStage1(p, diameter0, (alt0, az0))
        p2, _n2, _rms2, _radius2 = self._runStage2(p1, diameter0, rms1)

        final, n, rms, radius, partial = self._choosePartialOrFull(p1, p2, diameter0)
        self.fit_s += time.monotonic() - _t0

        return _buildFitResult(final, n, rms, radius, partial)

    def _refineResult(self, result):
        # re-run the fit anchored at its own solution until RMS stops
        # improving; azimuth is already known, so the coarse grid is
        # skipped. A failed restart is discarded -- refinement can polish
        # a success, never revoke one.
        for _restart in range(REFINE_MAX_RESTARTS):
            p = result['params']
            retry = self._runFitFrom(p.copy(), p[3], skip_coarse=True)
            if not retry['success']:
                break
            if retry['rms_px'] < result['rms_px'] - REFINE_MIN_RMS_IMPROVEMENT_PX:
                result = retry
            else:
                break
        return result
