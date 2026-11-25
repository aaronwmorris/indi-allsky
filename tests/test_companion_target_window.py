from datetime import datetime, timedelta, timezone
import math

import ephem
import numpy as np
import pytest

from indi_allsky.companion_target_window import (
    _forecast, _intervals, _observed_limits, _skyline, parse_window_settings, target_windows,
)


WHEN = datetime(2040, 11, 14, 18, 21, 22, tzinfo=timezone.utc)
SITE = (51.5, 0.0, 50)  # Example site on the Greenwich meridian.
M31 = (10.6847, 41.2688)
SQUID = (317.95075, 59.9858)
M42 = (83.8221, -5.3911)


def sample(target, stamp):
    obs = ephem.Observer()
    obs.lat, obs.lon = map(math.radians, SITE[:2])
    obs.elevation = SITE[2]
    obs.pressure = 0
    obs.date = stamp
    body = ephem.FixedBody()
    body._ra, body._dec = map(math.radians, target)
    body._epoch = ephem.J2000
    body.compute(obs)
    return obs, body, ephem.Sun(obs), ephem.Moon(obs)


def test_horizon_interpolates_across_north_and_wraps():
    normalized = parse_window_settings('{"horizon":[[350,40],[10,20],[120,0]]}')
    horizon = normalized['horizon']
    assert horizon[0] == [10, 20]
    assert _skyline([0, 5, 180, 359, 360], horizon) == pytest.approx([30, 25, 60 / 230 * 40, 31, 30])
    assert _skyline([0, 77, 220], [(25, 39)]) == pytest.approx([39, 39, 39])


def test_default_uses_the_natural_horizon_and_preserves_explicit_limits():
    assert parse_window_settings() == {'min_altitude': 0., 'moon_distance': 30., 'horizon': []}
    assert parse_window_settings({'min_altitude': 20})['min_altitude'] == 20


@pytest.mark.parametrize('raw', [False, 'null', '[]', {'min_altitude': -1}, {'min_altitude': True},
                                 {'moon_distance': 181}, {'foo': 2}, {'horizon': [[0, 1], [360, 2]]},
                                 {'horizon': [[2, float('nan')]]}, {'horizon': [[1]]},
                                 {'horizon': [[-1, 0]]}, {'horizon': [[1, 2]] * 73}])
def test_invalid_window_settings(raw):
    with pytest.raises(ValueError):
        parse_window_settings(raw)


def test_open_window_matches_independent_ephemeris_and_twilight():
    row = target_windows([SQUID], WHEN, *SITE, {'moon_distance': 0})[0]
    obs, body, _, _ = sample(SQUID, WHEN)
    assert row['state'] == 'open' and row['reason'] is None
    assert row['altitude_deg'] == pytest.approx(math.degrees(body.alt), abs=.06)
    assert row['azimuth_deg'] == pytest.approx(math.degrees(body.az), abs=.06)
    assert row['end_reason'] == 'twilight'
    obs.horizon = '-18'
    expected = obs.next_rising(ephem.Sun(), use_center=True).datetime().replace(tzinfo=timezone.utc)
    assert abs((datetime.fromisoformat(row['ends_at']) - expected).total_seconds()) < 15


def test_horizon_sets_window_end_and_below_horizon_uses_next_interval():
    up, later = target_windows([M31, M42], WHEN, *SITE, {'horizon': [[0, 40]], 'moon_distance': 0})
    assert up['state'] == 'open' and up['end_reason'] == 'horizon'
    assert up['limit_deg'] == 40
    _, body, _, _ = sample(M31, datetime.fromisoformat(up['ends_at']))
    assert math.degrees(body.alt) == pytest.approx(40, abs=.02)
    assert later['state'] == 'none' and later['reason'] == 'horizon'  # M42 never clears 40° here.
    later = target_windows([M42], WHEN, *SITE, {'moon_distance': 0, 'min_altitude': 20})[0]
    assert later['state'] == 'upcoming' and later['reason'] == 'altitude'
    for key in ('starts_at', 'ends_at'):
        _, body, _, _ = sample(M42, datetime.fromisoformat(later[key]))
        assert math.degrees(body.alt) == pytest.approx(20, abs=.02)


def test_moon_distance_only_blocks_if_moon_clears_skyline():
    # Use one circumpolar target and a separation threshold large enough to
    # trigger for any target. A narrow obstacle only blocks the Moon.
    stamp = datetime(2026, 11, 14, 18, 21, 22, tzinfo=timezone.utc)
    _, _, _, moon = sample(SQUID, stamp)
    moon_az = math.degrees(moon.az)
    assert math.degrees(moon.alt) > 0
    blocked = target_windows([SQUID], stamp, *SITE, {'moon_distance': 180})[0]
    assert blocked['state'] == 'upcoming' and blocked['reason'] == 'moon' and blocked['moon_up']
    obstacle = [[moon_az - 2, 0], [moon_az, 30], [moon_az + 2, 0]]
    open_now = target_windows([SQUID], stamp, *SITE, {'moon_distance': 180, 'horizon': obstacle})[0]
    assert open_now['state'] == 'open' and not open_now['moon_up']
    assert open_now['end_reason'] == 'moon'


def test_no_site_polar_summer_and_continuous_polar_night():
    unknown = target_windows([M31], WHEN, None, 0)[0]
    assert unknown['state'] == 'unknown' and unknown['reason'] == 'missing_location'
    polar_target = [(40., 85.)]
    polar = (89., 0, 0, {'moon_distance': 0})
    assert target_windows(polar_target, datetime(2040, 6, 21, tzinfo=timezone.utc), *polar)[0]['state'] == 'none'
    row = target_windows(polar_target, datetime(2040, 12, 21, tzinfo=timezone.utc), *polar)[0]
    assert row['state'] == 'open' and row['ends_at'] is None and row['end_reason'] == 'forecast_limit'


def test_multiple_matches_reuse_forecast_by_target_and_minute():
    _forecast.cache_clear()
    target_windows([M31, M42], WHEN, *SITE)
    target_windows([SQUID, M31], WHEN.replace(second=55), *SITE)
    info = _forecast.cache_info()
    assert (info.hits, info.misses) == (1, 3)


def test_contiguous_windows_stop_at_first_obstacle_and_resolve_opposing_limits():
    # One cell is blocked by different constraints at each end. A short window
    # exists between the crossings even though neither endpoint is available.
    gates = np.array([[1., 1., 1., 1.], [-1., 3., 1., 1.], [2., -2., 2., 2.], [1., 1., 1., 1.]])
    windows = _intervals(np.array([0, 60, 120, 180]), gates)
    assert windows == [(15., 30., 'horizon'), (90., None, 'forecast_limit')]


def observed(height, floor=lambda az: None):
    return {'step_deg': 2, 'altitudes': [height(i) for i in range(0, 360, 2)],
            'image_floor': [floor(i) for i in range(0, 360, 2)]}


def test_trajectory_stops_at_measured_crossing_and_reopens_beyond_it():
    stamp = datetime(2026, 11, 14, 19, 45, tzinfo=timezone.utc)
    ridge = observed(lambda az: 70 if 312 <= az <= 322 else 4)
    during = target_windows([SQUID], stamp, *SITE, observed_horizon=ridge)[0]
    assert (during['state'], during['end_reason'], during['horizon_basis']) == ('open', 'obstacle', 'image')
    assert during['reopens_at'] > during['ends_at']
    assert during['track_ends_at'] == during['ends_at'] and during['track_end_reason'] == 'obstacle'
    assert len(during['trajectory']) >= 3
    assert during['obstacle_crossing'] == during['trajectory'][-1]
    alt, az = during['obstacle_crossing']
    assert 310 < az < 312
    assert alt == pytest.approx(4 + (70-4) * (az-310) / 2, abs=.05)
    _, body, _, _ = sample(SQUID, datetime.fromisoformat(during['ends_at']))
    assert math.degrees(body.az) == pytest.approx(az, abs=.02)
    assert math.degrees(body.alt) == pytest.approx(alt, abs=.02)
    hidden = target_windows([SQUID], datetime.fromisoformat(during['ends_at']).timestamp() + 120,
                            *SITE, observed_horizon=ridge)[0]
    assert hidden['state'] == 'upcoming' and hidden['reason'] == 'obstacle'
    assert hidden['starts_at'] == during['reopens_at']
    assert hidden['track_starts_at'] == hidden['starts_at']


def test_blind_sector_and_cropped_image_have_distinct_bounds():
    # Wrapped rays next to north do not interpolate through a missing sector.
    heights = (30., None, None, 20.)
    floors = (None, 50., None, None)
    physical, verified = _observed_limits([0, 45, 90, 135, 270, 315], (heights, floors))
    assert np.allclose(physical, [30, np.nan, np.nan, np.nan, 20, 25], equal_nan=True)
    assert np.allclose(verified, [30, 50, 50, np.nan, 20, 25], equal_nan=True)

    stamp = datetime(2026, 11, 14, 19, 45, tzinfo=timezone.utc)
    partial = observed(lambda az: None if 312 <= az <= 335 else 0)
    row = target_windows([SQUID], stamp, *SITE, observed_horizon=partial)[0]
    assert row['state'] == 'open' and row['end_reason'] == 'unmapped'
    assert row['horizon_basis'] == 'partial' and row['obstacle_crossing'] is None and row['reopens_at'] is None
    assert row['track_end_reason'] == 'unmapped'

    # If the image confirms sky above a cropped lower edge, the high target is
    # observable there. If the entire open window is below that edge, its true
    # visibility is unknown (and cannot be reported as no window).
    row = target_windows([SQUID], stamp, *SITE,
                         observed_horizon=observed(lambda az: None, lambda az: 8))[0]
    assert row['state'] == 'open' and row['end_reason'] == 'twilight'
    row = target_windows([SQUID], stamp, *SITE,
                         observed_horizon=observed(lambda az: None, lambda az: 89))[0]
    assert (row['state'], row['reason'], row['horizon_basis']) == ('unknown', 'unmapped', 'partial')
    assert row['ends_at'] is None and row['trajectory'] == []


def test_missing_skyline_is_geometric_and_manual_horizon_still_limits():
    empty_profile = observed(lambda az: None)
    geometric = target_windows([M31], WHEN, *SITE, observed_horizon=empty_profile)[0]
    assert geometric['horizon_basis'] == 'geometric' and geometric['obstacle_crossing'] is None
    manual = target_windows([M31], WHEN, *SITE, {'horizon': [[0, 40]], 'moon_distance': 0},
                            observed_horizon=observed(lambda az: 5))[0]
    assert manual['end_reason'] == manual['track_end_reason'] == 'horizon'
    assert manual['obstacle_crossing'][0] == 40


def test_moon_only_hidden_by_measured_obstacle_not_by_unseen_image_floor():
    stamp = datetime(2026, 11, 14, 18, 21, 22, tzinfo=timezone.utc)
    _, _, _, moon = sample(SQUID, stamp)
    moon_az = math.degrees(moon.az)
    in_sector = lambda az: abs((az - moon_az + 180) % 360 - 180) < 10
    options = {'moon_distance': 180}
    physical = observed(lambda az: 40 if in_sector(az) else 0)
    blocked = target_windows([SQUID], stamp, *SITE, options, observed_horizon=physical)[0]
    assert not blocked['moon_up'] and blocked['state'] == 'open'
    clipped = observed(lambda az: None if in_sector(az) else 0, lambda az: 40 if in_sector(az) else None)
    row = target_windows([SQUID], stamp, *SITE, options, observed_horizon=clipped)[0]
    assert row['moon_up'] and row['reason'] == 'moon'


@pytest.mark.parametrize('when,settings,reason', [
    (WHEN, {'min_altitude': 20, 'moon_distance': 0}, 'altitude'),
    (WHEN.replace(day=7), {'min_altitude': 0, 'moon_distance': 0}, 'twilight'),
    (WHEN.replace(day=22), {'min_altitude': 0, 'moon_distance': 180}, 'moon'),
])
def test_track_ends_at_physical_horizon_after_photographic_window(when, settings, reason):
    row = target_windows([M31], when, *SITE, settings, observed_horizon=observed(lambda az: 15))[0]
    assert row['state'] == 'open' and row['end_reason'] == reason
    assert row['track_end_reason'] == 'obstacle' and row['track_ends_at'] > row['ends_at']
    assert row['trajectory'][-1] == row['obstacle_crossing']
    assert row['obstacle_crossing'][0] == 15
    _, body, _, _ = sample(M31, datetime.fromisoformat(row['track_ends_at']))
    assert math.degrees(body.alt) == pytest.approx(15., abs=.01)


def test_geometric_set_and_continuous_circumpolar_track():
    setting, circumpolar = target_windows([M42, SQUID], WHEN, *SITE, {'min_altitude': 35, 'moon_distance': 0})
    assert setting['track_end_reason'] == 'geometric_horizon'
    assert setting['trajectory'][-1] == setting['obstacle_crossing']
    assert setting['obstacle_crossing'][0] == 0
    assert circumpolar['track_end_reason'] == 'forecast_limit' and circumpolar['track_ends_at'] is None
    assert circumpolar['obstacle_crossing'] is None and len(circumpolar['trajectory']) > 10


def test_target_mark_overrides_a_high_skyline_and_keeps_other_targets_independent():
    # The same target on the same image can have a different observing limit
    # for a telescope beside the camera. The mark crosses midnight in UTC.
    at = datetime(2040, 11, 15, 0, 10, tzinfo=timezone.utc)
    marked, automatic = target_windows([SQUID, SQUID], WHEN, *SITE, {'moon_distance': 0},
                                       observed_horizon=observed(lambda az: 85),
                                       path_ends=[at.timestamp(), None], edit_path=0)
    assert marked['manual_end_status'] == 'applied'
    assert marked['state'] == 'open' and marked['end_reason'] == marked['track_end_reason'] == 'user_marked'
    assert marked['track_ends_at'] == marked['ends_at'] == at.isoformat()
    assert marked['obstacle_crossing'] == marked['trajectory'][-1]
    _, star, _, _ = sample(SQUID, at)
    assert marked['obstacle_crossing'] == pytest.approx([math.degrees(star.alt), math.degrees(star.az)], abs=.0001)
    assert automatic['state'] == 'none' and automatic['manual_end_status'] is None
    assert 'edit_directions' not in automatic
    assert len(marked['edit_times']) == len(marked['edit_directions']) == 289
    assert marked['edit_times'][0] == WHEN.isoformat() and marked['edit_times'][-1] > marked['ends_at']


@pytest.mark.parametrize('when,settings,reason', [
    (WHEN, {'min_altitude': 20, 'moon_distance': 0}, 'altitude'),
    (WHEN, {'moon_distance': 0}, 'twilight'),
    (WHEN.replace(day=22), {'moon_distance': 180}, 'moon'),
])
def test_late_target_mark_keeps_a_prior_photographic_limit(when, settings, reason):
    original = target_windows([M31], when, *SITE, settings)[0]
    end = datetime.fromisoformat(original['ends_at']).timestamp() + 300
    row = target_windows([M31], when, *SITE, settings, path_ends=[end])[0]
    assert row['manual_end_status'] == 'applied'
    assert row['end_reason'] == reason and row['ends_at'] == original['ends_at']
    assert row['track_end_reason'] == 'user_marked' and row['track_ends_at'] > row['ends_at']


def test_manual_mark_cannot_run_past_geometric_setting_or_reopen_after_it_expires():
    options = {'min_altitude': 0, 'moon_distance': 0}
    upcoming = target_windows([M42], WHEN, *SITE, options)[0]
    rise = datetime.fromisoformat(upcoming['track_starts_at']).timestamp()
    setting = datetime.fromisoformat(upcoming['track_ends_at']).timestamp()
    mark = rise + 3600
    for invalid in (rise - 120, setting + 120):
        row = target_windows([M42], WHEN, *SITE, options, path_ends=[invalid])[0]
        assert row['manual_end_status'] == 'outside_pass' and row['track_ends_at'] == upcoming['track_ends_at']
    point = target_windows([M42], mark + 120, *SITE, options, path_ends=[mark])[0]
    assert point['manual_end_status'] == 'expired' and point['state'] == 'none'
    assert point['reason'] == 'user_marked' and not point['trajectory']
    next_pass = target_windows([M42], setting + 120, *SITE, options, path_ends=[mark])[0]
    assert next_pass['manual_end_status'] == 'expired' and next_pass['state'] == 'upcoming'
    assert next_pass['track_end_reason'] == 'geometric_horizon'


@pytest.mark.parametrize('lat,target,expected', [
    (90, (20, 20), True), (90, (20, -20), False), (-90, (20, -20), True), (-90, (20, 20), False),
    (52, SQUID, True), (-52, SQUID, False), (0, (20, 89.9), False),
])
def test_circumpolar_uses_geometric_lower_culmination_at_this_site(lat, target, expected):
    row = target_windows([target], WHEN, lat, SITE[1], settings={'min_altitude': 85})[0]
    assert row['circumpolar'] is expected and row['track_reappears_at'] is None
    if expected:
        assert row['track_end_reason'] == 'forecast_limit' and row['track_ends_at'] is None
    if lat * target[1] < 0 and abs(lat) == 90:
        assert row['trajectory'] == []
    assert target_windows([target], WHEN, None, None)[0]['circumpolar'] is None


def test_grazing_lower_culmination_uses_current_apparent_declination():
    target = (174., 40.)
    dec = math.degrees(sample(target, WHEN)[1].dec)
    # Precession alone separates the date-of-observation and catalogue limits.
    assert abs(dec - target[1]) > .2
    for latitude, expected in [(90. - dec + .01, True), (90. - dec - .01, False)]:
        row = target_windows([target], WHEN, latitude, SITE[1])[0]
        assert row['circumpolar'] is expected


@pytest.mark.parametrize('source', ['measured', 'configured'])
def test_thin_branch_between_minute_ticks_closes_and_reopens_circumpolar_track(source):
    # The Greenwich track crosses a half-degree bearing between minute ticks.
    # Place a narrow branch on that bearing using an independent ephemeris.
    start = WHEN.replace(second=37)
    star = sample(SQUID, start + timedelta(seconds=15))[1]
    tip_index = round(math.degrees(star.az) * 2)
    bearing, peak = tip_index / 2, math.degrees(star.alt) + 6.
    heights = [20.] * 720
    heights[tip_index] = peak
    profile = {'step_deg': .5, 'altitudes': heights, 'image_floor': [None] * 720}
    settings = {'moon_distance': 0, 'min_altitude': 85}  # no photographic window here
    if source == 'configured':
        settings['horizon'] = [[bearing - .5, 20], [bearing, peak], [bearing + .5, 20]]
        profile = None
    row = target_windows([SQUID], start, *SITE, settings, observed_horizon=profile)[0]
    assert row['circumpolar'] and row['state'] == 'none'
    assert row['track_end_reason'] == ('obstacle' if profile else 'horizon')
    sets = (datetime.fromisoformat(row['track_ends_at']) - start).total_seconds()
    rises = (datetime.fromisoformat(row['track_reappears_at']) - start).total_seconds()
    assert 0 < sets < rises < 25 and 5 < rises - sets < 18
    for delta, above in [(sets - 2, True), ((sets + rises) / 2, False), (rises + 2, True)]:
        body = sample(SQUID, start + timedelta(seconds=delta))[1]
        az, alt = math.degrees(body.az), math.degrees(body.alt)
        obstruction = peak - abs(az - bearing) * (peak - 20.) / .5
        assert (alt > obstruction) is above
    if profile:
        # A cropped bearing immediately beyond the branch masks its exit edge.
        # Finding confirmed sky later does not establish when the object reappeared.
        heights[tip_index - 1] = None
        cropped = target_windows([SQUID], start, *SITE, settings, observed_horizon=profile)[0]
        assert cropped['track_end_reason'] == 'obstacle' and cropped['track_reappears_at'] is None


def test_circumpolar_clear_mark_restores_automatic_track_and_next_night_is_independent():
    options = {'moon_distance': 0}
    end_at = datetime(2040, 11, 15, 0, 5, tzinfo=timezone.utc).timestamp()
    rows = target_windows([SQUID, SQUID], end_at + 60, *SITE, options, path_ends=[end_at, None])
    assert rows[0]['circumpolar'] and rows[0]['manual_end_status'] == 'expired'
    assert rows[0]['reason'] == 'user_marked' and rows[0]['track_reappears_at'] is None
    assert rows[1]['state'] == 'open' and rows[1]['end_reason'] == 'twilight'
    assert rows[1]['track_end_reason'] == 'forecast_limit'
    restored = target_windows([SQUID], end_at + 60, *SITE, options)[0]
    assert restored == rows[1]
    tomorrow = target_windows([SQUID], end_at + 86460, *SITE, options, path_ends=[end_at])[0]
    assert tomorrow['manual_end_status'] == 'out_of_range' and tomorrow['state'] == 'open'


def test_closed_display_envelope_sets_window_and_track_inside_unmeasured_sector():
    start = datetime(2026, 11, 14, 19, 45, tzinfo=timezone.utc)
    raw = observed(lambda az: None if 310 <= az <= 324 else 4)
    row = target_windows([SQUID], start, *SITE, observed_horizon=raw)[0]
    assert row['horizon_basis'] == 'partial' and row['track_end_reason'] == 'unmapped'
    raw['envelope'] = [70 if 312 <= az <= 322 else 4 for az in range(0, 360, 2)]
    estimated = target_windows([SQUID], start, *SITE, observed_horizon=raw)[0]
    assert estimated['horizon_basis'] == 'estimated' and estimated['circumpolar']
    assert estimated['track_end_reason'] == estimated['end_reason'] == 'obstacle'
    assert estimated['track_ends_at'] == estimated['ends_at'] > row['track_ends_at']
    assert estimated['track_reappears_at'] == estimated['reopens_at'] > estimated['ends_at']
    height, az = estimated['obstacle_crossing']
    assert 310 < az < 312 and raw['altitudes'][int(az // 2)] is None
    assert height == pytest.approx(np.interp(az, np.arange(0, 360, 2), raw['envelope'], period=360), abs=.001)
    during = datetime.fromisoformat(estimated['ends_at']).timestamp() + 120
    hidden = target_windows([SQUID], during, *SITE, observed_horizon=raw)[0]
    assert hidden['reason'] == 'obstacle' and hidden['starts_at'] == estimated['reopens_at']
    manual = target_windows([SQUID], start, *SITE, observed_horizon=raw, path_ends=[during])[0]
    assert manual['end_reason'] == manual['track_end_reason'] == 'user_marked'


def test_clear_circumpolar_pass_has_no_false_setting_on_closed_outline():
    raw = observed(lambda az: 8 if az < 250 else None)
    raw['envelope'] = [8.] * 180
    row = target_windows([(0., 89.)], WHEN, *SITE, {'moon_distance': 0}, observed_horizon=raw)[0]
    assert row['circumpolar'] and row['horizon_basis'] == 'estimated'
    assert row['track_end_reason'] == 'forecast_limit' and row['end_reason'] == 'twilight'
    assert row['track_ends_at'] is row['track_reappears_at'] is row['obstacle_crossing'] is None
    for invalid in (None, [8.], [float('nan')] * 180):
        raw['envelope'] = invalid
        fallback = target_windows([(0., 89.)], WHEN, *SITE, observed_horizon=raw)[0]
        assert fallback['horizon_basis'] == 'partial'


def test_first_registered_image_can_supply_an_estimate_without_repeatable_physical_edges():
    first = observed(lambda az: None)
    first.update(frames=1, quality='estimated', envelope=[85.] * 180)
    row = target_windows([SQUID], WHEN, *SITE, observed_horizon=first)[0]
    assert row['horizon_basis'] == 'estimated' and row['reason'] == 'obstacle'
    assert row['limit_deg'] == 85.
