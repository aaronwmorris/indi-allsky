"""Local observing-night ephemerides for the camera companion."""

import math
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError

import ephem


def camera_timezone(camera):
    """Use the camera's timezone rules when available, including DST changes."""
    if camera.local:
        system_zone = os.environ.get('TZ', '').lstrip(':')
        if system_zone and not os.path.isabs(system_zone):
            try:
                return ZoneInfo(system_zone)
            except (ZoneInfoNotFoundError, ValueError):
                pass

        zone_file = Path(system_zone if os.path.isabs(system_zone) else '/etc/localtime')
        try:
            # Raspberry Pi OS normally links /etc/localtime to an IANA TZif.
            # Preserve that key so the browser can apply the same DST rules.
            target = zone_file.resolve()
            key = None
            for root in TZPATH:
                database = Path(root).resolve()
                if target.is_relative_to(database):
                    key = target.relative_to(database).as_posix()
                    key = key.removeprefix('posix/').removeprefix('right/')
                    break
            # For a copied /etc/localtime the transitions still work without a key.
            with zone_file.open('rb') as stream:
                return ZoneInfo.from_file(stream, key=key)
        except (OSError, ValueError, RuntimeError):
            pass

    # Capture commonly saves abbreviations like CET or CST. These do not
    # uniquely identify the remote location's DST rules.
    name = camera.tz or ''
    if '/' in name or name in ('UTC', 'GMT'):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass

    return timezone(timedelta(seconds=camera.utc_offset or 0))


def _event(method, body, start, tz, *, center=False, stop=None):
    try:
        event = method(body, start=ephem.Date(start), use_center=center)
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return None

    utc = event.datetime().replace(tzinfo=timezone.utc)
    if stop is not None and utc >= stop:
        return None
    return utc.astimezone(tz).isoformat(timespec='seconds')


def _moon_phase(local_now, moon, sun):
    # Name the exact quarter on its camera-local calendar day.
    day_start = datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    for event, name in ((ephem.next_new_moon, 'New Moon'),
                        (ephem.next_first_quarter_moon, 'First Quarter'),
                        (ephem.next_full_moon, 'Full Moon'),
                        (ephem.next_last_quarter_moon, 'Last Quarter')):
        stamp = event(day_start).datetime().replace(tzinfo=timezone.utc)
        if stamp.astimezone(local_now.tzinfo).date() == local_now.date():
            return name

    angle = (float(ephem.Ecliptic(moon).lon) - float(ephem.Ecliptic(sun).lon)) % math.tau
    names = ('Waxing Crescent', 'Waxing Gibbous', 'Waning Gibbous', 'Waning Crescent')
    return names[int(angle / (math.pi / 2))]


def night_ephemeris(now, tz, latitude, longitude, elevation):
    """Return twilight for local noon-to-noon and upcoming lunar events.

    evening_start/end are descending solar-center crossings at -12/-18°.
    morning_start/end are ascending crossings at -18/-12°. Lunar rise/set
    are the next respective crossings after now, independent of civil date.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    local_now = now.astimezone(tz)
    utc_now = now.astimezone(timezone.utc)
    day = local_now.date() if local_now.hour >= 12 else local_now.date() - timedelta(days=1)
    start = datetime.combine(day, time(12), tzinfo=tz).astimezone(timezone.utc)
    stop = datetime.combine(day + timedelta(days=1), time(12), tzinfo=tz).astimezone(timezone.utc)

    moon = ephem.Moon(utc_now)
    sun = ephem.Sun(utc_now)
    result = dict.fromkeys(('evening_start', 'evening_end', 'morning_start', 'morning_end',
                            'moon_rise', 'moon_set'))
    result['moon_phase'] = _moon_phase(local_now, moon, sun)
    result['moon_illumination'] = round(moon.moon_phase * 100, 1)
    if latitude is None or longitude is None:
        return result

    obs = ephem.Observer()
    obs.lat = math.radians(latitude)
    obs.lon = math.radians(longitude)
    obs.elevation = elevation or 0
    obs.pressure = 0

    for horizon, evening, morning in (('-12', 'evening_start', 'morning_end'),
                                      ('-18', 'evening_end', 'morning_start')):
        obs.horizon = horizon
        result[evening] = _event(obs.next_setting, sun, start, tz, center=True, stop=stop)
        result[morning] = _event(obs.next_rising, sun, start, tz, center=True, stop=stop)

    # Upper lunar limb at the standard refracted horizon (34 arcminutes).
    obs.horizon = '-0:34'
    result['moon_rise'] = _event(obs.next_rising, moon, utc_now, tz)
    result['moon_set'] = _event(obs.next_setting, moon, utc_now, tz)
    return result
