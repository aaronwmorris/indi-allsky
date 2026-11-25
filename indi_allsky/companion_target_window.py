"""Geometric imaging windows for J2000 targets at a moving camera station."""
from datetime import datetime, timezone
from functools import lru_cache
import json
import math

import ephem
import numpy as np


_LOOKAHEAD = 24 * 3600
_REASONS = ('twilight', 'altitude', 'horizon', 'moon', 'obstacle', 'unmapped')


def _number(value, low, high, name):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f'{name} must be a number between {low} and {high}.')
    return float(value)


def parse_window_settings(raw=None):
    """Normalize a camera's user-supplied horizon (degrees clockwise from north)."""
    if raw is None:
        raw = {}
    if isinstance(raw, str):
        if len(raw) > 6000:
            raise ValueError('Window settings are too long.')
        raw = json.loads(raw)
    if not isinstance(raw, dict) or set(raw) - {'min_altitude', 'moon_distance', 'horizon'}:
        raise ValueError('Invalid window settings.')
    horizon = raw.get('horizon', [])
    if not isinstance(horizon, (list, tuple)) or len(horizon) > 72:
        raise ValueError('The horizon can contain up to 72 azimuth and altitude pairs.')
    points = {}
    for pair in horizon:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('Each horizon point requires an azimuth and an altitude.')
        az = _number(pair[0], 0, 360, 'Horizon azimuth') % 360
        if az in points:
            raise ValueError('Each horizon azimuth must be unique (360° is north).')
        points[az] = _number(pair[1], 0, 90, 'Horizon altitude')
    return {'min_altitude': _number(raw.get('min_altitude', 0), 0, 90, 'Minimum altitude'),
            'moon_distance': _number(raw.get('moon_distance', 30), 0, 180, 'Moon distance'),
            'horizon': [[az, points[az]] for az in sorted(points)]}


def _skyline(azimuth, horizon):
    if not horizon:
        return np.zeros_like(azimuth)
    az, alt = zip(*horizon)
    return np.interp(azimuth, az, alt, period=360.)


def _image_profile(profile):
    """Convert an internal, equally spaced north-clockwise profile to a cache key."""
    if profile is None:
        return None, 'geometric'
    heights, floors = tuple(profile['altitudes']), tuple(profile['image_floor'])
    if (not heights or len(floors) != len(heights)
            or not math.isclose(profile['step_deg'] * len(heights), 360.)):
        raise ValueError('An image horizon must cover 360 degrees in equal steps.')
    envelope = profile.get('envelope')
    if envelope is not None and len(envelope) == len(heights):
        if all(isinstance(v, (int, float, np.integer, np.floating)) and 0 <= v <= 90 for v in envelope):
            # Use exactly the closed outline drawn on the frame for the track,
            # the imaging window and their crossings, including inferred terrain.
            return (tuple(envelope), floors), 'estimated'
    if all(x is None for x in heights + floors):
        return None, 'geometric'
    return (heights, floors), 'image' if None not in heights else 'partial'


def _observed_limits(azimuth, profile):
    """Physical skyline and lower limit of verified sky, without bridging blind sectors."""
    measured, floors = (np.asarray(values, dtype=float) for values in profile)
    pos = np.asarray(azimuth) % 360. * (len(measured) / 360.)
    cell = np.floor(pos).astype(int)
    part = pos - cell
    left = cell % len(measured)
    right = np.where(part == 0, left, (left + 1) % len(measured))
    a, b = measured[left], measured[right]
    physical = a + part * (b - a)
    # Across a clipped image edge, both bordering rays must confirm visibility.
    # Missing data on either ray propagates instead of inventing an obstacle.
    lower_a = np.where(np.isfinite(a), a, floors[left])
    lower_b = np.where(np.isfinite(b), b, floors[right])
    verified = np.where(np.isfinite(physical), physical, np.maximum(lower_a, lower_b))
    return physical, verified


def _observer(lat, lon, elevation):
    obs = ephem.Observer()
    obs.lat, obs.lon = math.radians(lat), math.radians(lon)
    obs.elevation = elevation
    obs.pressure = 0  # Use geometric solar, lunar and target centers consistently.
    return obs


def _target(ra, dec):
    body = ephem.FixedBody()
    body._ra, body._dec = math.radians(ra), math.radians(dec)
    body._epoch = ephem.J2000
    return body


@lru_cache(maxsize=104)
def _sky_hour(hour, site):
    """One-minute ephemerides, reused for all targets and successive frames."""
    obs = _observer(*site)
    sun, moon = ephem.Sun(), ephem.Moon()
    rows = []
    for stamp in range(hour, hour + 3600, 60):
        obs.date = datetime.fromtimestamp(stamp, timezone.utc)
        sun.compute(obs)
        moon.compute(obs)
        rows.append((float(obs.sidereal_time()), math.degrees(sun.alt), math.degrees(moon.alt),
                     math.degrees(moon.az), float(moon.ra), float(moon.dec)))
    return np.array(rows)


@lru_cache(maxsize=6)
def _sky_grid(start, site):
    hour = start // 3600 * 3600
    offset = (start - hour) // 60
    count = (offset + 1442 + 59) // 60
    hours = [_sky_hour(hour + i * 3600, site) for i in range(count)]
    return np.concatenate(hours)[offset:offset + 1442].T


def _distance(ra, dec, moon_ra, moon_dec):
    cosine = np.sin(dec) * np.sin(moon_dec) + np.cos(dec) * np.cos(moon_dec) * np.cos(ra - moon_ra)
    return np.degrees(np.arccos(np.clip(cosine, -1, 1)))


def _margins(alt, az, sun_alt, moon_alt, moon_az, separation, min_alt, moon_dist, horizon, profile,
             marked=False):
    skyline = _skyline(az, () if marked else horizon)
    moon_horizon = _skyline(moon_az, horizon)
    limit = np.maximum(min_alt, skyline)
    if profile is not None:
        moon_obstacle, _ = _observed_limits(moon_az, profile)
        moon_horizon = np.fmax(moon_horizon, moon_obstacle)
    if profile is not None and not marked:
        obstacle, verified = _observed_limits(az, profile)
        limit = np.fmax(limit, obstacle)
    margins = [-18. - sun_alt, alt - min_alt, alt - skyline,
               np.maximum(moon_horizon - moon_alt, separation - moon_dist)]
    if profile is not None and not marked:
        # Physical crossings close windows. Crossing the image floor only ends
        # the portion we can verify. An unobserved Moon is never assumed hidden.
        margins.append(np.where(np.isfinite(obstacle), alt - obstacle, 180.))
        margins.append(np.where(np.isfinite(obstacle), 1.,
                                np.where(np.isfinite(verified), alt - verified, -180.)))
    return np.array(margins), limit, moon_alt > moon_horizon


def _intervals(times, margins, reasons=_REASONS):
    """Intersect linearly interpolated constraints within each sample interval."""
    left, right = margins[:, :-1], margins[:, 1:]
    with np.errstate(invalid='ignore', divide='ignore'):
        crossing = left / (left - right)
    enters = np.where((left < 0) & (right >= 0), crossing, 0.)
    exits = np.where((left >= 0) & (right < 0), crossing, 1.)
    enter, leave = enters.max(axis=0), exits.min(axis=0)
    valid = ((left >= 0) | (right >= 0)).all(axis=0) & (enter < leave)
    contiguous = valid[:-1] & valid[1:] & (leave[:-1] == 1.) & (enter[1:] == 0.)
    first = np.flatnonzero(valid & ~np.r_[False, contiguous])
    last = np.flatnonzero(valid & ~np.r_[contiguous, False])
    step = np.diff(times)
    windows = []
    for a, b in zip(first, last):
        start = float(times[a] + enter[a] * step[a])
        if b == len(step) - 1 and leave[b] == 1.:
            windows.append((start, None, 'forecast_limit'))
        else:
            end = float(times[b] + leave[b] * step[b])
            reason = exits[:, b].argmin() if leave[b] < 1. else right[:, b].argmin()
            windows.append((start, end, reasons[reason]))
    return windows


def _sight_gates(profile, horizon):
    ground = 'horizon' if horizon else 'geometric_horizon'
    if profile is None:
        return [2], [ground]
    return [4, 5, 2], ['obstacle', 'unmapped', ground]


def _from_now(stamp, intervals):
    return [(max(s, stamp), e, r) for s, e, r in intervals if e is None or e > stamp]


def _horizon_times(minutes, hour_angle, lat, dec, horizon, profile):
    """Sample both sides of each azimuth knot, including a thin branch between minute ticks."""
    azimuths = [az for az, _ in horizon]
    if profile:
        azimuths.extend(np.arange(len(profile[0])) * (360. / len(profile[0])))
    if not azimuths:
        return minutes
    az = np.radians(np.unique(azimuths))
    # A target on a given bearing satisfies east*cos(az) - north*sin(az) = 0.
    # Solve for its hour angles and keep all crossings within this forecast.
    a = math.cos(dec) * np.cos(az)
    b = -math.cos(dec) * math.sin(lat) * np.sin(az)
    c = -math.sin(dec) * math.cos(lat) * np.sin(az)
    amplitude = np.hypot(a, b)
    valid = (amplitude > 1e-12) & (abs(c) <= amplitude)
    phase = np.arctan2(b[valid], a[valid])
    root = np.arcsin(c[valid] / amplitude[valid])
    turns = (np.r_[root - phase, np.pi - root - phase] - hour_angle[0]) % (2 * np.pi)
    turns = np.r_[turns, turns + 2 * np.pi] + hour_angle[0]
    edges = np.interp(turns[turns <= hour_angle[-1]], hour_angle, minutes)
    # At a measured/cropped boundary visibility may jump. Bracket that
    # discontinuity locally instead of smearing it across the whole minute.
    samples = np.r_[minutes, edges - .05, edges, edges + .05]
    return np.unique(np.clip(samples, minutes[0], minutes[-1]))


@lru_cache(maxsize=384)
def _forecast(ra, dec, start, site, min_alt, moon_dist, horizon, profile, marked=False):
    # Use apparent coordinates of date. Their change during one day is much
    # smaller than this forecast's minute sampling and a hand-drawn horizon.
    obs = _observer(*site)
    obs.date = datetime.fromtimestamp(start, timezone.utc)
    body = _target(ra, dec)
    body.compute(obs)
    lst, sun_alt, moon_alt, moon_az, moon_ra, moon_dec = _sky_grid(start, site)
    hour_angle = np.unwrap(lst) - float(body.ra)
    decl = float(body.dec)
    minutes = np.arange(start, start + _LOOKAHEAD + 61, 60)
    times = _horizon_times(minutes, hour_angle, obs.lat, decl, horizon, profile) if not marked else minutes
    if len(times) > len(minutes):
        hour_angle, sun_alt, moon_alt, moon_az, moon_ra, moon_dec = (
            np.interp(times, minutes, values) for values in
            (hour_angle, sun_alt, moon_alt, np.degrees(np.unwrap(np.radians(moon_az))),
             np.unwrap(moon_ra), moon_dec))
    sin_lat, cos_lat = math.sin(obs.lat), math.cos(obs.lat)
    sin_dec, cos_dec = math.sin(decl), math.cos(decl)
    north = sin_dec * cos_lat - cos_dec * sin_lat * np.cos(hour_angle)
    east = -cos_dec * np.sin(hour_angle)
    up = sin_dec * sin_lat + cos_dec * cos_lat * np.cos(hour_angle)
    altitude = np.degrees(np.arctan2(up, np.hypot(east, north)))
    azimuth = np.degrees(np.arctan2(east, north)) % 360.
    separation = _distance(float(body.ra), decl, moon_ra, moon_dec)
    margins, _, _ = _margins(altitude, azimuth, sun_alt, moon_alt, moon_az, separation,
                              min_alt, moon_dist, horizon, profile, marked)
    windows = _intervals(times, margins)
    gates, reasons = _sight_gates(None, ()) if marked else _sight_gates(profile, horizon)
    visible = _intervals(times, margins[gates], reasons)
    possible = None
    if not marked and profile is not None and None in profile[0]:
        # Unknown parts of the image can conceal a reopening. Check whether
        # known terrain alone accounts for the entire gap between two passes.
        possible = _intervals(times, margins[[4, 2]], ['obstacle', 'horizon'])
        # A single azimuth ray at an unknown boundary cannot establish even
        # one full forecast second of usable sky. Retain real brief obstructions.
        windows = [(s, e, r) for s, e, r in windows if e is None or e - s >= 1.]
        visible = [(s, e, r) for s, e, r in visible if e is None or e - s >= 1.]
    could_be_open = bool(possible is not None and not windows and _intervals(times, margins[:-1]))
    return windows, visible, could_be_open, possible


def _iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='seconds') if stamp is not None else None


def _trajectory(ra, dec, site, first, last):
    """Bounded, apparent topocentric track including the opening and closing positions."""
    count = min(73, max(2, math.ceil((last - first) / 600) + 1))
    return target_directions(ra, dec, site, np.linspace(first, last, count))


def target_directions(ra, dec, site, times):
    obs, body = _observer(*site), _target(ra, dec)
    path = []
    for stamp in times:
        obs.date = datetime.fromtimestamp(stamp, timezone.utc)
        body.compute(obs)
        path.append([round(math.degrees(body.alt), 4), round(math.degrees(body.az), 4) % 360])
    return path


def _geometric_pass(ra, dec, site, stamp):
    """One uninterrupted pass above 0°, starting now or at the next rising."""
    obs, body = _observer(*site), _target(ra, dec)
    obs.date = datetime.fromtimestamp(stamp, timezone.utc)
    body.compute(obs)
    limit = stamp + _LOOKAHEAD
    first = stamp
    try:
        if body.alt <= 0:
            obs.date = obs.next_rising(body, use_center=True)
            first = obs.date.datetime().replace(tzinfo=timezone.utc).timestamp()
        end = obs.next_setting(body, use_center=True).datetime().replace(tzinfo=timezone.utc).timestamp()
    except ephem.AlwaysUpError:
        end = limit
    except ephem.NeverUpError:
        return None
    return (first, min(limit, end)) if first < min(limit, end) else None


def _horizon_track(ra, dec, site, visible, stamp, horizon, profile):
    """Draw only one uninterrupted visible pass. Twilight and Moon do not hide the track."""
    limit = stamp + _LOOKAHEAD
    if not visible or visible[0][0] >= limit:
        return dict(trajectory=[], obstacle_crossing=None, track_starts_at=None,
                    track_ends_at=None, track_end_reason=None)
    first, last, reason = visible[0]
    if last is None or last > limit:
        last, reason = limit, 'forecast_limit'
    path = _trajectory(ra, dec, site, first, last)
    crossing = None
    if reason in ('obstacle', 'horizon', 'geometric_horizon'):
        # Put the endpoint on the actual contour. The time comes from the sampled
        # ephemeris; a setting at 0° must not vanish one pixel below the lens rim.
        az = path[-1][1]
        height = _observed_limits(az, profile)[0] if reason == 'obstacle' else _skyline(az, horizon)
        if np.isfinite(height):
            crossing = path[-1] = [round(float(height), 4), az]
        else:
            reason = 'unmapped'
    return dict(trajectory=path, obstacle_crossing=crossing, track_starts_at=_iso(first),
                track_ends_at=_iso(last) if reason != 'forecast_limit' else None, track_end_reason=reason)


def target_windows(coordinates, when, latitude, longitude, elevation=0, settings=None, *,
                   observed_horizon=None, path_ends=None, edit_path=None):
    """Current or next continuous observing interval in 24h for each target.

    Times are UTC, the horizon and Moon criterion are geometric, and window
    edges are estimates from a one-minute grid. Never extrapolate a closing
    time past the 24h forecast. No network, image or plate solution is needed.
    """
    options = parse_window_settings(settings)
    min_alt, moon_dist = options['min_altitude'], options['moon_distance']
    horizon = tuple(map(tuple, options['horizon']))
    profile, basis = _image_profile(observed_horizon)
    if isinstance(when, datetime):
        if when.tzinfo is None:
            raise ValueError('The time for target windows requires a UTC offset.')
        when = when.timestamp()
    stamp = float(when)
    if not math.isfinite(stamp):
        raise ValueError('Invalid time for target windows.')
    if (type(latitude) not in (int, float) or not -90 <= latitude <= 90 or
            type(longitude) not in (int, float) or not -180 <= longitude <= 180):
        return [dict(state='unknown', reason='missing_location', starts_at=None, ends_at=None,
                     end_reason=None, altitude_deg=None, azimuth_deg=None, moon_distance_deg=None,
                     sun_altitude_deg=None, moon_up=None, limit_deg=None, horizon_basis='geometric',
                     trajectory=[], obstacle_crossing=None, reopens_at=None, track_starts_at=None,
                     track_ends_at=None, track_end_reason=None, circumpolar=None,
                     track_reappears_at=None) for _ in coordinates]
    site = (latitude, longitude, elevation or 0.)
    obs = _observer(*site)
    obs.date = datetime.fromtimestamp(stamp, timezone.utc)
    sun, moon = ephem.Sun(obs), ephem.Moon(obs)
    sun_alt, moon_alt, moon_az = map(math.degrees, (sun.alt, moon.alt, moon.az))
    start = math.floor(stamp / 60) * 60
    results = []
    for index, (ra, dec) in enumerate(coordinates):
        body = _target(ra, dec)
        body.compute(obs)
        alt, az = math.degrees(body.alt), math.degrees(body.az)
        # Altitude at lower culmination, using the apparent declination at this
        # date. This also works at either geographic pole and excludes grazes.
        circumpolar = abs(latitude + math.degrees(body.dec)) > 90.
        end_at = path_ends[index] if path_ends else None
        status = None
        editor = {}
        visible_pass = None
        if edit_path == index or end_at is not None:
            visible_pass = _geometric_pass(ra, dec, site, stamp)
        if edit_path == index:
            times = []
            if visible_pass:
                first, last = visible_pass
                times = np.linspace(first, last, max(2, math.ceil((last - first) / 300.) + 1))
            editor = dict(edit_times=[_iso(t) for t in times], edit_directions=target_directions(ra, dec, site, times))
        expired_here = False
        if end_at is not None:
            if not math.isfinite(end_at) or abs(end_at - stamp) > _LOOKAHEAD:
                status = 'out_of_range'
            elif end_at <= stamp:
                status = 'expired'
                # A previous setting belongs to one passage only. A target that
                # has since set and risen begins a fresh observing window.
                last_pass = _geometric_pass(ra, dec, site, end_at)
                expired_here = bool(last_pass and last_pass[0] == end_at and stamp < last_pass[1])
            elif visible_pass and visible_pass[0] <= end_at <= visible_pass[1]:
                status = 'applied'
            else:
                status = 'outside_pass'
        marked = status == 'applied'
        separation = _distance(float(body.ra), float(body.dec), float(moon.ra), float(moon.dec))
        current, limit, moon_up = _margins(alt, az, sun_alt, moon_alt, moon_az, separation,
                                           min_alt, moon_dist, horizon, profile, marked)
        forecast, visible_forecast, could_be_open, possible = _forecast(
            ra, dec, start, site, min_alt, moon_dist, horizon, profile, marked)
        windows = _from_now(stamp, forecast)
        reappears = None
        if marked:
            windows = [(s, e, r) if e is not None and e < end_at else (s, end_at, 'user_marked')
                       for s, e, r in windows if s < end_at]
            first = visible_pass[0]
            path = _trajectory(ra, dec, site, first, end_at)
            track = dict(trajectory=path, obstacle_crossing=path[-1], track_starts_at=_iso(first),
                         track_ends_at=_iso(end_at), track_end_reason='user_marked')
        else:
            visible = _from_now(stamp, visible_forecast)
            track = _horizon_track(ra, dec, site, visible, stamp, horizon, profile)
            if (circumpolar and track['track_end_reason'] in ('obstacle', 'horizon')
                    and len(visible) > 1 and visible[1][0] < stamp + _LOOKAHEAD):
                sets, rises = visible[0][1], visible[1][0]
                if possible is None or not any(
                        s < rises and (e is None or e > sets) for s, e, _ in possible):
                    reappears = rises
        reason = None
        altitude_limits = (1, 2, 4) if profile is not None and not marked else (1, 2)
        lowest_margin = min(altitude_limits, key=current.__getitem__)
        if current[0] < 0:
            reason = 'twilight'
        elif current[lowest_margin] < 0:
            reason = _REASONS[lowest_margin]
        elif current[3] < 0:
            reason = 'moon'
        elif profile is not None and not marked and current[5] < 0:
            reason = 'unmapped'
        state, opens, closes, end_reason = 'none', None, None, None
        reopens = None
        if windows and windows[0][0] < stamp + _LOOKAHEAD:
            opens, closes, end_reason = windows[0]
            state = 'open' if opens <= stamp else 'upcoming'
            if closes is None or closes > stamp + _LOOKAHEAD:
                closes, end_reason = None, 'forecast_limit'
            if end_reason == 'obstacle' and len(windows) > 1 and windows[1][0] < stamp + _LOOKAHEAD:
                reopens = windows[1][0]
        if reason == 'unmapped' or (state == 'none' and could_be_open):
            state, reason = 'unknown', 'unmapped'
        if expired_here:
            state, reason = 'none', 'user_marked'
            reappears = None
            opens, closes, end_reason, reopens = None, end_at, 'user_marked', None
            track = dict(trajectory=[], obstacle_crossing=None, track_starts_at=None,
                         track_ends_at=_iso(end_at), track_end_reason='user_marked')
        results.append(dict(state=state, reason=reason, starts_at=_iso(opens), ends_at=_iso(closes),
                            end_reason=end_reason, altitude_deg=round(alt, 1), azimuth_deg=round(az, 1) % 360,
                            moon_distance_deg=round(float(separation), 1), moon_up=bool(moon_up),
                            sun_altitude_deg=round(sun_alt, 1), limit_deg=round(float(limit), 1),
                            horizon_basis=basis, reopens_at=_iso(reopens), manual_end_status=status,
                            circumpolar=circumpolar, track_reappears_at=_iso(reappears), **track, **editor))
    return results
