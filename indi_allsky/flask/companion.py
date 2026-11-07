from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import abort, render_template, request, session
from sqlalchemy.orm.exc import NoResultFound

from ..companion_astronomy import camera_timezone, night_ephemeris
from .base_views import BaseView
from .companion_charts import companion_charts
from .misc import login_optional_media


class CompanionView(BaseView):
    decorators = [login_optional_media]

    def dispatch_request(self):
        camera_id = request.args.get('camera_id', type=int)
        if camera_id is None:
            camera_id = session.get('camera_id')
        if camera_id is None:
            try:
                camera_id = self.getLatestCamera().id
            except NoResultFound:
                camera_id = -1

        period = float(self.indi_allsky_config.get('CCD_EXPOSURE_MAX', 15))
        cadence = max(period, float(self.indi_allsky_config.get('EXPOSURE_PERIOD') or 0),
                      float(self.indi_allsky_config.get('EXPOSURE_PERIOD_DAY') or 0))
        return render_template(
            'companion.html',
            camera_id=camera_id,
            refresh_ms=int(min(30, max(5, period + 1)) * 1000),
            stale_ms=int(max(90, 2 * cadence + 15) * 1000),
        )


def companion_status(view):
    camera_id = request.args.get('camera_id', type=int)
    if camera_id is None:
        abort(400)
    view.cameraSetup(camera_id=camera_id, include_sunset=False)
    if view.camera.id < 1:
        abort(404)

    zone = camera_timezone(view.camera)
    now = datetime.now(timezone.utc).astimezone(zone)
    data = {
        'camera_id': view.camera.id,
        'now': now.isoformat(),
        'time_zone': getattr(zone, 'key', None),
        'offset_minutes': int(now.utcoffset().total_seconds() / 60),
        'capture_paused': bool(view.camera.capture_pause),
        'image': latest_companion_image(view, now),
    }
    # The browser can discover a published frame promptly without recomputing
    # two hours of sensor readings and the ephemerides on each image check.
    if request.args.get('image_only') == '1':
        return data

    latitude, longitude = view.getCameraPrivacyLatLong(view.camera)
    data['astronomy'] = night_ephemeris(now, zone, latitude, longitude, view.camera.elevation or 0)
    data['metrics'], data['defaults'], data['series'] = companion_charts(
        view.camera, view.indi_allsky_config, now, zone, request.args.getlist('metric'),
        local_images_allowed=view.local_images_allowed,
    )
    return data


def latest_companion_image(view, now):
    # Use one database entry for both the URL and its capture time. Keep the
    # last eligible image across long pauses, ignoring future-dated captures.
    entry = view.getLatestImage(view.camera.id, None, not_after=now.replace(tzinfo=None))
    image = None
    captured = None
    if entry.get('url'):
        wall_time = entry['create_date']
        offset = entry.get('utc_offset')
        if isinstance(offset, (int, float)) and -86400 < offset < 86400:
            captured = wall_time.replace(tzinfo=timezone(timedelta(seconds=offset)))
        else:
            captured = wall_time.replace(tzinfo=now.tzinfo)
            other = captured.replace(fold=1)
            if other.utcoffset() != captured.utcoffset() and other.timestamp() <= now.timestamp():
                captured = other
        image = {'url': entry['url'], 'captured_at': captured.isoformat(), 'time_source': 'capture'}

    # Focus mode and unsaved daytime frames can exist only as latest.<ext>.
    # It is one local file for the active device, never a remote-camera asset.
    uses_live_file = view.indi_allsky_config.get('FOCUS_MODE') or (view.daytime_capture and not view.daytime_capture_save)
    if not uses_live_file or not view.live_file_allowed:
        return image

    filename = 'latest.' + view.indi_allsky_config.get('IMAGE_FILE_TYPE', 'jpg')
    try:
        stamp = (Path(view.indi_allsky_config['IMAGE_FOLDER']) / filename).stat()
    except OSError:
        return image
    if stamp.st_mtime > now.timestamp() or (captured and stamp.st_mtime <= captured.timestamp()):
        return image
    return {
        'url': 'images/{0}?v={1}'.format(filename, stamp.st_mtime_ns),
        'captured_at': datetime.fromtimestamp(stamp.st_mtime, now.tzinfo).isoformat(),
        'time_source': 'file',
    }
