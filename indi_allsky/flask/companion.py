from datetime import datetime, timedelta, timezone
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
import re

from flask import abort, current_app, jsonify, make_response, render_template, request, session
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound

from ..companion_astronomy import camera_timezone, night_ephemeris
from ..companion_battery import battery_reading
from ..companion_targets import (
    OnlineCatalogUnavailable, UnknownTargetName, marker_coordinates, project_horizon_line, project_targets,
    resolve_coordinates, resolve_name,
)
from .base_views import BaseView
from .companion_charts import companion_charts, sensor_probes
from .companion_horizon import observed_horizon, setup_id
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
        details = 'target_settings' in request.args
        frame = request.args.get('frame', type=int)
        if (not details or 'frame' in request.args) and (frame is None or not 0 < frame <= 2**63 - 1):
            raise ValueError('Invalid image ID.')
        coordinates = marker_coordinates(request.args.getlist('target'))
        if not details and any(key in request.args for key in ('path_end_at', 'path_end_setup', 'edit_path')):
            raise ValueError('Editing a target path requires window settings.')
        if details:
            from ..companion_target_window import parse_window_settings
            settings = parse_window_settings(request.args['target_settings'])
            path_ends, edit_index, path_setup = companion_path_options(request.args, len(coordinates))
    except UnknownTargetName as exc:
        code = 'online_unknown' if online else 'unknown_name'
        abort(make_response(jsonify(error=str(exc), code=code), 400))
    except OnlineCatalogUnavailable as exc:
        abort(make_response(jsonify(error=str(exc), code='catalog_unavailable'), 503))
    except ValueError as exc:
        abort(make_response(jsonify(error=str(exc)), 400))

    if details and view.camera.hidden:
        abort(404)
    result = {'frame': frame, 'state': 'unavailable', 'points': [None] * len(coordinates)}
    entry, model = companion_frame(view, frame) if frame is not None else (None, None)
    if entry is not None:
        points = project_targets(coordinates, model)
        if points is None:
            result['state'] = 'orientation_pending'
        else:
            result.update(state='ready', points=points)
    if not details:
        return result

    from ..companion_target_window import target_directions, target_windows
    when = datetime.now(timezone.utc)
    latitude, longitude = view.getCameraPrivacyLatLong(view.camera)
    profile = None
    plan_model = None
    result['qualities'] = [
        {'state': 'unknown', 'reason': 'An accessible, star-aligned night image is required.', 'matched': 0, 'expected': 0}
        for _ in coordinates
    ]
    if result['state'] == 'ready':
        # Forecasts use the current sky. A stale frame from a mobile rig may
        # show the previous setup, even if its own target markers remain valid.
        age = when.timestamp() - model['observed_at']
        if (latitude is not None and longitude is not None
                and abs(latitude - model['location'][0]) <= .03
                and abs((longitude - model['location'][1] + 180) % 360 - 180) <= .03
                and -5 <= age <= max(180, 3 * (entry.exposure or 0) + 60)):
            plan_model = model
        if view.camera.local and view.local_images_allowed:
            from ..companion_target_quality import assess_targets
            path = companion_archive_path(entry)
            result['qualities'] = assess_targets(path, model, coordinates, night=entry.night,
                                                exposure=entry.exposure, gain=entry.gain)
            if plan_model is not None and entry.night and path is not None:
                profile = companion_observed_horizon(view, entry, model)

    setup = setup_id(entry, plan_model) if plan_model else None
    rejected = {}
    site = (latitude, longitude, view.camera.elevation or 0)
    for index, end in enumerate(path_ends):
        if end is None:
            continue
        if not setup:
            rejected[index] = 'unavailable'
        elif path_setup != setup:
            rejected[index] = 'setup_changed'
        elif abs(end - plan_model['observed_at']) > 86400 or abs(end - when.timestamp()) > 86400:
            rejected[index] = 'out_of_range'
        else:
            position = target_directions(*coordinates[index], site, [end])[0]
            if position[0] < 0:
                rejected[index] = 'outside_pass'
            elif project_horizon_line(plan_model, [position])[0] is None:
                rejected[index] = 'outside_image'
        if index in rejected:
            path_ends[index] = None
    windows = target_windows(coordinates, when, *site, settings, observed_horizon=profile,
                             path_ends=path_ends, edit_path=edit_index if plan_model else None)
    for index, window in enumerate(windows):
        directions = window.pop('trajectory', [])
        crossing = window.pop('obstacle_crossing', None)
        window['track'] = project_horizon_line(plan_model, directions) if plan_model else []
        window['intersection'] = project_horizon_line(plan_model, [crossing])[0] if crossing and plan_model else None
        window['manual_end_status'] = rejected.get(index, window.get('manual_end_status'))
        if index == edit_index:
            times = window.pop('edit_times', [])
            positions = project_horizon_line(plan_model, window.pop('edit_directions', [])) if plan_model else []
            window['edit_path'] = [dict(at=at, **p) if p else None for at, p in zip(times, positions)]
    skyline = project_horizon_line(plan_model, skyline_directions(profile)) if profile is not None else []
    zone = camera_timezone(view.camera)
    result.update(window_at=when.isoformat(), windows=windows, skyline=skyline, setup_id=setup,
                  skyline_source_frame_id=profile.get('source_frame_id') if profile else None,
                  time_zone=getattr(zone, 'key', None), offset_minutes=int(when.astimezone(zone).utcoffset().total_seconds() / 60))
    return result


def skyline_directions(profile):
    """Close the estimated silhouette at north, using the same bearings as the forecast."""
    envelope = profile.get('envelope')
    if envelope is not None and len(envelope):
        points = [(height, i * profile['step_deg']) for i, height in enumerate(envelope)]
        return points + points[:1]
    # If the detector could only substantiate isolated patches, draw those on their own.
    heights = profile['altitudes']
    if not heights:
        return []
    contour = []
    previous = None
    for i in range(len(heights) + 1):
        index = i % len(heights)
        height = heights[index]
        # A large jump on adjacent rays is a gap between measured edges.
        # Connecting their tips would draw a diagonal through open sky.
        if previous is not None and height is not None and abs(height - previous) > 3.:
            contour.append(None)
        contour.append((height, index * profile['step_deg']) if height is not None else None)
        previous = height
    return contour


def companion_path_options(args, count):
    values = args.getlist('path_end_at')
    if values and len(values) != count:
        raise ValueError('Send one path end per target, leaving unmarked targets empty.')
    ends = []
    for value in values:
        if not value:
            ends.append(None)
        elif len(value) <= 32 and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}'
                                             r'(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|\+00:00)', value):
            try:
                ends.append(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
            except (ValueError, OSError, OverflowError):
                raise ValueError('Enter a valid UTC date and time for the path end.') from None
        else:
            raise ValueError('Enter the path end as an ISO 8601 UTC date and time.')
    index = args.get('edit_path')
    if index is not None:
        if len(args.getlist('edit_path')) != 1 or not re.fullmatch(r'[0-9]{1,2}', index) or int(index) >= count:
            raise ValueError('Choose one target in this request to edit.')
        index = int(index)
    setup = args.get('path_end_setup')
    if setup is not None and (len(args.getlist('path_end_setup')) != 1 or len(setup) > 64):
        raise ValueError('Invalid observing setup.')
    return ends, index, setup


def companion_frame(view, frame):
    query = view.model.query.filter_by(camera_id=view.camera.id, id=frame)
    if not view.local_images_allowed:
        query = query.filter(or_(view.model.remote_url != '', view.model.s3_key != ''))
    entry = query.first()
    if entry is None:
        return None, None
    try:
        url = entry.getUrl(s3_prefix=view.s3_prefix, local=view.local_images_allowed)
    except ValueError:
        return None, None
    if not url or (isinstance(url, Path) and url.is_absolute()):
        return None, None

    # The companion also runs on stations without automatic stellar alignment.
    from . import views
    frame_alignment = getattr(views, 'virtualsky_frame_alignment', None)
    if frame_alignment is None:
        return None, None
    model = frame_alignment(view, entry) if isinstance(entry.data, dict) else None
    return entry, model


def companion_archive_path(entry):
    try:
        path = Path(entry.getFilesystemPath()).resolve(strict=True)
        path.relative_to(Path(current_app.config['INDI_ALLSKY_IMAGE_FOLDER']).resolve(strict=True))
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def companion_observed_horizon(view, entry, model):
    return observed_horizon(view, entry, model, companion_archive_path)


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
