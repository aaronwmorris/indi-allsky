from datetime import datetime, timedelta, timezone
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from flask import abort, jsonify, make_response, render_template, request, session
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound

from ..companion_astronomy import camera_timezone, night_ephemeris
from ..companion_battery import battery_reading
from ..companion_targets import (
    OnlineCatalogUnavailable, UnknownTargetName, marker_coordinates, project_targets,
    resolve_coordinates, resolve_name,
)
from .base_views import BaseView
from .companion_charts import companion_charts, sensor_probes
from .misc import login_optional_media


def _station_module(name):
    # Older installations can serve the Companion without these station services.
    return import_module(name) if find_spec(name) is not None else None


archive_health = _station_module('indi_allsky.archive_health')
sensor_health = _station_module('indi_allsky.sensor_health')
star_alignment = _station_module('indi_allsky.star_alignment')


def local_station_status(view):
    status = {}
    blocked = False
    if not (view.local_indi_allsky and view.local_images_allowed):
        return status, blocked

    if archive_health is not None:
        archive = archive_health.archive_state(view.indi_allsky_config)
        blocked = archive.get('level') == archive_health.BLOCKED
        # Only publish the reason code. Paths and other host details stay local.
        status['archive'] = archive.get('reason', 'ok')
    if sensor_health is not None:
        status['ups_unreadable'] = sensor_health.ups_problem(Path('/run/indi-allsky-ups-watchdog/health.json'))
    if star_alignment is not None and view.indi_allsky_config.get('CARDINAL_DIRS', {}).get('AUTO_ALIGN'):
        try:
            active_id = view._miscDb.getState('DB_CAMERA_ID')
        except NoResultFound:
            active_id = None
        if active_id == str(view.camera.id):
            status['orientation'] = star_alignment.read_alignment_status(view.indi_allsky_config, view.camera.uuid)
    return status, blocked


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

    if any(key in request.args for key in ('resolve', 'ra', 'dec', 'frame', 'target')):
        return companion_target_request(view)

    zone = camera_timezone(view.camera)
    now = datetime.now(timezone.utc).astimezone(zone)
    image_only = request.args.get('image_only') == '1'
    station_status, blocked = local_station_status(view)
    entry = {} if blocked else view.getLatestImage(
        view.camera.id, None, not_after=now.replace(tzinfo=None), include_sensor_data=not image_only,
    )
    data = {
        'camera_id': view.camera.id,
        'now': now.isoformat(),
        'time_zone': getattr(zone, 'key', None),
        'offset_minutes': int(now.utcoffset().total_seconds() / 60),
        'capture_paused': bool(view.camera.capture_pause),
        'image': None if blocked else latest_companion_image(view, now, entry),
        **station_status,
    }
    # The browser can discover a published frame promptly without recomputing
    # two hours of sensor readings and the ephemerides on each image check.
    if image_only:
        return data

    data['battery'] = battery_reading(
        sensor_probes(view.camera, view.indi_allsky_config), entry.get('sensor_data'), data['image'],
        now, view.camera, view.indi_allsky_config,
    )

    latitude, longitude = view.getCameraPrivacyLatLong(view.camera)
    data['astronomy'] = night_ephemeris(now, zone, latitude, longitude, view.camera.elevation or 0)
    data['metrics'], data['defaults'], data['series'] = companion_charts(
        view.camera, view.indi_allsky_config, now, zone, request.args.getlist('metric'),
        local_images_allowed=view.local_images_allowed,
    )
    return data


def companion_target_request(view):
    online = request.args.get('online') == '1'
    try:
        if 'resolve' in request.args:
            return {'target': resolve_name(request.args['resolve'], online=online)}
        if 'ra' in request.args or 'dec' in request.args:
            return {'target': resolve_coordinates(request.args.get('ra'), request.args.get('dec'))}
        frame = request.args.get('frame', type=int)
        if frame is None or not 0 < frame <= 2**63 - 1:
            raise ValueError('Invalid image ID.')
        coordinates = marker_coordinates(request.args.getlist('target'))
    except UnknownTargetName as exc:
        code = 'online_unknown' if online else 'unknown_name'
        abort(make_response(jsonify(error=str(exc), code=code), 400))
    except OnlineCatalogUnavailable as exc:
        abort(make_response(jsonify(error=str(exc), code='catalog_unavailable'), 503))
    except ValueError as exc:
        abort(make_response(jsonify(error=str(exc)), 400))

    result = {'frame': frame, 'state': 'unavailable', 'points': [None] * len(coordinates)}
    query = view.model.query.filter_by(camera_id=view.camera.id, id=frame)
    if not view.local_images_allowed:
        query = query.filter(or_(view.model.remote_url != '', view.model.s3_key != ''))
    entry = query.first()
    if entry is None:
        return result
    try:
        url = entry.getUrl(s3_prefix=view.s3_prefix, local=view.local_images_allowed)
    except ValueError:
        return result
    if not url or (isinstance(url, Path) and url.is_absolute()):
        return result

    # The companion also runs on stations without automatic stellar alignment.
    from . import views
    frame_alignment = getattr(views, 'virtualsky_frame_alignment', None)
    if frame_alignment is None:
        return result
    model = frame_alignment(view, entry) if isinstance(entry.data, dict) else None
    points = project_targets(coordinates, model)
    if points is None:
        result['state'] = 'orientation_pending'
    else:
        result.update(state='ready', points=points)
    return result


def latest_companion_image(view, now, entry):
    # Use one database entry for both the URL and its capture time. Keep the
    # last eligible image across long pauses, ignoring future-dated captures.
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
        if entry.get('id') is not None:
            image['id'] = entry['id']

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
