import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import TZPATH, ZoneInfo

import ephem
import pytest

from indi_allsky.companion_astronomy import camera_timezone, night_ephemeris


BERLIN = ZoneInfo('Europe/Berlin')
TWILIGHT = ('evening_start', 'evening_end', 'morning_start', 'morning_end')


def test_midnight_keeps_previous_evening_until_noon():
    def times(stamp):
        data = night_ephemeris(datetime.fromisoformat(stamp).replace(tzinfo=BERLIN),
                               BERLIN, 48, 8, 250)
        return [datetime.fromisoformat(data[key]) for key in TWILIGHT]

    original = times('2026-11-07T21:00')
    assert times('2026-11-08T00:05') == original
    assert times('2026-11-08T11:59') == original
    assert times('2026-11-08T12:00')[0].date() == original[0].date() + timedelta(days=1)
    assert original == sorted(original)

    # At each published time the geometric solar center is on the named horizon.
    obs = ephem.Observer()
    obs.lat, obs.lon, obs.elevation, obs.pressure = math.radians(48), math.radians(8), 250, 0
    for stamp, altitude in zip(original, (-12, -18, -18, -12)):
        obs.date = stamp
        assert math.degrees(ephem.Sun(obs).alt) == pytest.approx(altitude, abs=0.01)


@pytest.mark.parametrize(('evening', 'offsets'), [
    ('2026-03-28T21:00', (1, 2)),
    ('2026-10-24T21:00', (2, 1)),
])
def test_dst_transition_uses_event_specific_offset(evening, offsets):
    now = datetime.fromisoformat(evening).replace(tzinfo=BERLIN)
    data = night_ephemeris(now, BERLIN, 48, 8, 0)
    evening_end = datetime.fromisoformat(data['evening_end'])
    morning_start = datetime.fromisoformat(data['morning_start'])
    assert evening_end.utcoffset() == timedelta(hours=offsets[0])
    assert morning_start.utcoffset() == timedelta(hours=offsets[1])
    assert morning_start.date() == evening_end.date() + timedelta(days=1)


@pytest.mark.parametrize('month', [6, 12])
def test_no_seasonal_crossings_attached_to_a_polar_night(month):
    now = datetime(2026, month, 21, 19, tzinfo=timezone.utc)
    data = night_ephemeris(now, timezone.utc, 89, 0, 2)
    assert all(data[key] is None for key in TWILIGHT)
    assert data['moon_rise'] is None
    assert data['moon_set'] is None
    assert 0 <= data['moon_illumination'] <= 100


def test_polar_night_can_still_have_twilight():
    tz = ZoneInfo('Arctic/Longyearbyen')
    now = datetime(2026, 12, 21, 20, tzinfo=tz)
    data = night_ephemeris(now, tz, 78.2, 15.6, 30)
    # Sun stays below the ordinary horizon but crosses both twilight thresholds.
    assert all(data[key] is not None for key in TWILIGHT)
    assert data['moon_rise'] is None and data['moon_set'] is None


def test_lunar_events_are_future_events_with_dates():
    now = datetime(2026, 10, 24, 21, tzinfo=BERLIN)
    data = night_ephemeris(now, BERLIN, 48, 8, 0)
    rise = datetime.fromisoformat(data['moon_rise'])
    setting = datetime.fromisoformat(data['moon_set'])
    assert now < setting < rise
    assert rise.date() == setting.date() == now.date() + timedelta(days=1)
    assert rise.utcoffset() == setting.utcoffset() == timedelta(hours=1)
    assert data['moon_phase'] == 'Waxing Gibbous'
    assert 95 < data['moon_illumination'] < 100


def test_full_moon_name_uses_camera_calendar_date_without_coordinates():
    instant = ephem.next_full_moon('2026/11/1').datetime().replace(tzinfo=timezone.utc)
    tz = ZoneInfo('Pacific/Auckland')
    now = instant.astimezone(tz).replace(hour=0, minute=0, second=0)
    data = night_ephemeris(now, tz, None, None, None)
    assert data['moon_phase'] == 'Full Moon'
    assert 98 < data['moon_illumination'] <= 100
    assert all(data[key] is None for key in (*TWILIGHT, 'moon_rise', 'moon_set'))


def test_timezone_prefers_local_system_rules_or_remote_zone(monkeypatch):
    camera = SimpleNamespace(local=True, tz='CEST', utc_offset=7200)
    monkeypatch.setenv('TZ', 'Europe/Berlin')
    tz = camera_timezone(camera)
    assert datetime(2026, 1, 1, tzinfo=tz).utcoffset() == timedelta(hours=1)
    assert datetime(2026, 7, 1, tzinfo=tz).utcoffset() == timedelta(hours=2)

    camera.local, camera.tz = False, 'America/New_York'
    assert camera_timezone(camera) == ZoneInfo('America/New_York')
    camera.tz = 'CST'
    assert camera_timezone(camera) == timezone(timedelta(hours=2))


def test_localtime_key_for_symlink_and_rules_for_copied_file(tmp_path, monkeypatch):
    camera = SimpleNamespace(local=True, tz='CET', utc_offset=3600)
    berlin = next(Path(root, 'Europe/Berlin') for root in TZPATH
                  if Path(root, 'Europe/Berlin').is_file())
    localtime = tmp_path / 'localtime'
    localtime.symlink_to(berlin)
    monkeypatch.setenv('TZ', ':' + str(localtime))
    assert camera_timezone(camera).key == 'Europe/Berlin'

    localtime.unlink()
    localtime.write_bytes(berlin.read_bytes())
    tz = camera_timezone(camera)
    assert tz.key is None
    assert datetime(2026, 7, 1, tzinfo=tz).utcoffset() == timedelta(hours=2)
