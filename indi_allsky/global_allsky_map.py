"""Optional AllskyTeam map client. No capture code, image upload or host ID access."""
import hashlib
import ipaddress
import json
import math
import platform
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

import psutil

from .version import __version__

ENDPOINT = 'https://www.thomasjacquin.com/allsky-map/postToMap.php'
ID_KEY = 'GLOBAL_MAP_ID'
STATE_KEY = 'GLOBAL_MAP_STATE'
ACTION = 'publishGlobalAllskyMap'
REFRESH_SECONDS = 48 * 3600
QUOTA_SECONDS = 24 * 3600
MIN_INTERVAL = 60
MAX_UPDATES = 5
TIMEOUT = 15
MAX_RESPONSE = 8192


class MapError(ValueError):
    pass


class _AlreadyAttempted(MapError):
    pass


class _MetadataChanged(MapError):
    pass


class _Disabled(MapError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_urls(website, image):
    """Image alone is valid; a website requires an image on the same host."""
    hosts = []
    for value in (website, image):
        if not isinstance(value, str):
            raise MapError('Public URLs must be text')
        if not value:
            hosts.append(None)
            continue
        if value != value.strip() or any(ord(c) < 33 for c in value):
            raise MapError('Public URLs must not contain spaces or control characters')
        try:
            parts = parse.urlsplit(value)
            host = parts.hostname
            parts.port  # Validate the optional port without rewriting the URL.
        except ValueError as exc:
            raise MapError('Invalid public URL') from exc
        if parts.scheme not in ('http', 'https') or not host or parts.username is not None or parts.password is not None or parts.fragment:
            raise MapError('Use public HTTP(S) URLs without credentials or fragments')
        if host.lower() == 'localhost' or host.lower().endswith('.local'):
            raise MapError('Public URLs must be reachable outside the local network')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise MapError('Public URLs must not contain private/local IP addresses')
        hosts.append(host.lower().removeprefix('www.'))
    if website and not image:
        raise MapError('Website URL requires an Image URL')
    if website and hosts[0] != hosts[1]:
        raise MapError('Website and Image URLs must use the same domain')


def coordinate(value, latitude, private=False):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise MapError('Invalid map coordinates') from exc
    if not math.isfinite(value) or abs(value) > (90 if latitude else 180):
        raise MapError('Map coordinates are outside their valid range')
    # Same whole-degree privacy convention as BaseView; otherwise public map precision.
    value = round(value, 0 if private else 2)
    direction = ('N' if value >= 0 else 'S') if latitude else ('E' if value >= 0 else 'W')
    magnitude = format(abs(value), '.2f').rstrip('0').rstrip('.')
    return magnitude + direction


def computer_description():
    try:
        model = Path('/proc/device-tree/model').read_text().strip('\x00\r\n ')
    except OSError:
        model = 'Generic PC ({0})'.format(platform.machine())
    try:
        ram = '{0:.0f} GiB'.format(psutil.virtual_memory().total / 1024**3)
    except (OSError, psutil.Error):
        ram = 'RAM unavailable'
    return '{0}, {1}'.format(model or 'Unknown computer', ram)


def payload(config, camera, identifier, computer=None):
    """Build an explicit metadata allowlist; never serialize config/camera objects."""
    if not re.fullmatch('[0-9a-f]{32}', identifier):
        raise MapError('Invalid installation identifier; it must not be regenerated')
    if camera is None or not camera.local:
        raise MapError('No active local camera metadata is available')
    metadata = camera.data if isinstance(camera.data, dict) else {}
    name = metadata.get('detected_name') or camera.name
    if not name:
        raise MapError('Detected camera name is unavailable')
    options = config.get('GLOBAL_ALLSKY_MAP', {})
    website = config.get('WEBSITE', {}).get('PUBLIC_URL', '')
    image = options.get('IMAGE_URL', '')
    validate_urls(website, image)
    private = bool(config.get('PRIVACY_MODE'))
    return {
        'force': False, 'machine_id': identifier,
        'location': str(config.get('LOCATION_NAME', '') or ''),
        'owner': str(config.get('OWNER', '') or ''),
        'latitude': coordinate(config.get('LOCATION_LATITUDE'), True, private),
        'longitude': coordinate(config.get('LOCATION_LONGITUDE'), False, private),
        'website_url': website, 'image_url': image, 'camera': str(name),
        'lens': str(config.get('LENS_NAME', '') or ''),
        'computer': computer if computer is not None else computer_description(),
        'equipmentinfo': str(options.get('EQUIPMENT', '') or ''),
        'allsky_version': __version__, 'website_settings': {}, 'allsky_settings': {},
    }


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def parse_response(text, deleting=False):
    messages = []
    terminal = None
    for line in text.splitlines():
        if not line.startswith('RETURN '):
            continue
        fields = line.split(None, 2)
        if len(fields) < 2:
            raise MapError('Malformed map response')
        status = fields[1]
        detail = fields[2] if len(fields) == 3 else ''
        if status == 'MESSAGE':
            messages.append(detail[:300])
            continue
        if status not in ('INSERTED', 'UPDATED', 'DELETED', 'ERROR', 'ALREADY_UPDATED') or terminal is not None:
            raise MapError('Unexpected map response status')
        terminal = {'status': status, 'message': detail[:300], 'messages': messages}
        if status == 'UPDATED' and detail:
            counts = detail.split()
            if len(counts) != 2 or not all(n.isdecimal() for n in counts):
                raise MapError('Malformed update counts')
            terminal['updates'], terminal['maximum'] = map(int, counts)
        if status == 'ALREADY_UPDATED' and detail.isdecimal():
            terminal['maximum'] = int(detail)
    if terminal is None:
        raise MapError('No terminal RETURN status in map response')
    if terminal['status'] in ('INSERTED', 'UPDATED', 'DELETED'):
        if (terminal['status'] == 'DELETED') != deleting:
            raise MapError('Map response does not match the requested operation')
    terminal['ok'] = terminal['status'] in ('INSERTED', 'UPDATED', 'DELETED')
    return terminal


def post(data, opener=None):
    """One bounded attempt. No redirects, image fetches or automatic retries."""
    req = request.Request(ENDPOINT, data=json.dumps(data).encode('utf-8'), method='POST', headers={
        'Accept': 'application/json', 'Content-Type': 'application/json',
        'User-Agent': 'indi-allsky/' + __version__,
    })
    opener = opener or request.build_opener(_NoRedirect()).open
    try:
        with opener(req, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise MapError('Map HTTP status {0}'.format(response.status))
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise MapError('Map response exceeds the size limit')
            return parse_response(body.decode('utf-8', errors='replace'), data.get('website_url') == 'DELETE')
    except error.HTTPError as exc:
        raise MapError('Map HTTP error {0}'.format(exc.code)) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise MapError('Transport failed or timed out; outcome may be unknown. No retry was made.') from exc


class GlobalMapService:
    """Existing state/task tables own identity, deduplication and attempt history."""
    def __init__(self, config_loader=None, clock=None, opener=None):
        self.config_loader = config_loader
        self.clock = clock or time.time
        self.opener = opener

    def config(self):
        if self.config_loader:
            return self.config_loader()
        from .config import IndiAllSkyConfig
        return IndiAllSkyConfig().config

    def _read(self, key):
        from .flask.models import IndiAllSkyDbStateTable
        row = IndiAllSkyDbStateTable.query.filter_by(key=key).populate_existing().first()
        return row.value if row else None

    def _ensure(self, key, value):
        from .flask import db
        from .flask.models import IndiAllSkyDbStateTable
        from sqlalchemy.exc import IntegrityError
        if self._read(key) is None:
            db.session.add(IndiAllSkyDbStateTable(key=key, value=value))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()  # Another request created the unique row first.
        return self._read(key)

    def identifier(self, create=False):
        value = self._read(ID_KEY)
        if value is None and create:
            value = self._ensure(ID_KEY, secrets.token_hex(16))
        if value is not None and not re.fullmatch('[0-9a-f]{32}', value):
            raise MapError('Stored installation identifier is invalid; refusing to replace it')
        return value

    def state(self):
        try:
            value = json.loads(self._read(STATE_KEY) or '{}')
            if not isinstance(value, dict):
                raise ValueError('not an object')
            return value
        except ValueError as exc:
            raise MapError('Stored map state is invalid; refusing to replace it') from exc

    def _change(self, change):
        """CAS keeps concurrent WebUI/task claims from creating duplicate POSTs."""
        from .flask import db
        from .flask.models import IndiAllSkyDbStateTable
        self._ensure(STATE_KEY, '{}')
        for _ in range(4):
            old = self._read(STATE_KEY)
            state = json.loads(old)
            try:
                result = change(state)
            except Exception:
                db.session.rollback()
                raise
            value = json.dumps(state, sort_keys=True, separators=(',', ':'))
            if len(value) > 4096:
                db.session.rollback()
                raise MapError('Map state exceeds storage limit')
            updated = IndiAllSkyDbStateTable.query.filter_by(key=STATE_KEY, value=old).update({
                'value': value, 'createDate': datetime.now(timezone.utc).replace(tzinfo=None),
            }, synchronize_session=False)
            if updated:
                db.session.commit()
                return result
            db.session.rollback()
        raise MapError('Map state is busy; try again')

    def _payload(self, config, create=False):
        from .flask.models import IndiAllSkyDbCameraTable
        identifier = self.identifier(create)
        if identifier is None:
            raise MapError('Preview registration first')
        try:
            camera_id = int(self._read('DB_CAMERA_ID') or '')
        except ValueError as exc:
            raise MapError('No active local camera metadata is available') from exc
        camera = IndiAllSkyDbCameraTable.query.filter_by(id=camera_id, local=True).first()
        return payload(config, camera, identifier)

    def preview(self):
        data = self._payload(self.config(), create=True)
        token = fingerprint(data)
        data['machine_id'] = '(installation identifier hidden)'
        return {'metadata': data, 'preview_token': token, 'status': self.status()}

    def status(self):
        state = self.state()
        # Do not expose the identifier, task claim internals or full server messages.
        public = {k: state.get(k) for k in ('registered', 'pending', 'last_status', 'last_success', 'last_attempt', 'needs_review', 'quota')}
        pending = state.get('pending')
        if pending and state.get('attempted_task') == pending:
            from .flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueState
            task = IndiAllSkyDbTaskQueueTable.query.filter_by(id=pending).first()
            if not task or task.state in (TaskQueueState.EXPIRED, TaskQueueState.FAILED):
                public['needs_review'] = True
                public['last_status'] = 'Interrupted request; manual review required, not retried'
        public['dirty'] = False
        if state.get('registered'):
            try:
                public['dirty'] = fingerprint(self._payload(self.config())) != state.get('payload_hash')
            except MapError as exc:
                public['metadata_error'] = str(exc)
        return public

    def _budget(self, state, force, removing=False):
        now = self.clock()
        attempts = [a for a in state.get('attempts', []) if now - a['time'] < QUOTA_SECONDS]
        if not force and sum(not a['force'] for a in attempts) >= MAX_UPDATES:
            raise MapError('Five ordinary attempts in the last 24 hours; wait for quota or explicitly force an update')
        if not removing and now - state.get('last_attempt', -QUOTA_SECONDS) < MIN_INTERVAL:
            raise MapError('Wait one minute between map requests')
        return attempts

    def enqueue(self, operation, preview_token=None, automatic=False):
        from .flask import db
        from .flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueState, TaskQueueQueue
        if operation not in ('register', 'update', 'force', 'remove') or (automatic and operation != 'update'):
            raise MapError('Invalid map operation')
        config = self.config()
        if operation != 'remove' and not config.get('GLOBAL_ALLSKY_MAP', {}).get('ENABLE', False):
            raise MapError('Global Allsky Map is disabled')
        if operation == 'remove':
            if self.identifier() is None:
                raise MapError('No installation registration identifier exists')
            digest = None
        else:
            digest = fingerprint(self._payload(config))
            if not automatic and preview_token != digest:
                raise MapError('Preview the saved metadata before publication')
        def queue(state):
            if automatic and (not state.get('registered') or state.get('needs_review')):
                return None
            if operation == 'remove' and not state.get('registered') and str(state.get('last_status', '')).startswith('DELETED'):
                raise MapError('The map entry was already removed')
            pending = state.get('pending')
            if pending:
                task = db.session.get(IndiAllSkyDbTaskQueueTable, pending)
                if task and task.state in (TaskQueueState.MANUAL, TaskQueueState.QUEUED, TaskQueueState.RUNNING):
                    if operation == 'remove' and task.data['kwargs']['operation'] != 'remove':
                        if state.get('attempted_task') == pending:
                            raise MapError('Disabled; publication is in progress. Retry removal after it finishes.')
                        task.state = TaskQueueState.EXPIRED
                    else:
                        return pending
                elif automatic and state.get('attempted_task') == pending:
                    state['needs_review'] = True
                    state['last_status'] = 'Interrupted request; manual review required, not retried'
                    return None
            self._budget(state, operation == 'force', operation == 'remove')
            job = IndiAllSkyDbTaskQueueTable(queue=TaskQueueQueue.VIDEO, state=TaskQueueState.MANUAL,
                priority=100, data={'action': ACTION, 'kwargs': {'operation': operation, 'payload_hash': digest}})
            db.session.add(job)
            db.session.flush()
            state['pending'] = job.id
            state['last_status'] = 'Queued ' + operation
            return job.id
        return self._change(queue)

    def schedule(self):
        config = self.config()
        if not config.get('GLOBAL_ALLSKY_MAP', {}).get('ENABLE', False):
            return None
        state = self.state()
        if not state.get('registered') or state.get('needs_review'):
            return None
        pending = state.get('pending')
        if pending:
            from .flask import db
            from .flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueState
            task = db.session.get(IndiAllSkyDbTaskQueueTable, pending)
            if task and task.state in (TaskQueueState.MANUAL, TaskQueueState.QUEUED, TaskQueueState.RUNNING):
                return None
            def reconcile(current):
                if current.get('pending') != pending:
                    return
                if current.get('attempted_task') == pending:
                    current['needs_review'] = True
                    current['last_status'] = 'Interrupted request; manual review required, not retried'
                else:
                    # Parent restart expires queued jobs. A never-attempted job is safe
                    # to replace; the old task can no longer claim the pending slot.
                    current.pop('pending', None)
            self._change(reconcile)
            state = self.state()
            if state.get('pending') or state.get('needs_review'):
                return None
        if self.clock() < state.get('auto_not_before', 0):
            return None
        data = self._payload(config)
        if fingerprint(data) == state.get('payload_hash') and self.clock() - state.get('last_success', 0) < REFRESH_SECONDS:
            return None
        return self.enqueue('update', automatic=True)

    def execute(self, task, operation, payload_hash=None):
        """Only the background worker calls this; record the attempt before I/O."""
        from .flask import db
        now = self.clock()
        identifier = None
        try:
            if operation not in ('register', 'update', 'force', 'remove'):
                raise MapError('Invalid queued operation')
            identifier = self.identifier()
            config = self.config()  # Fresh saved config, not the worker's startup snapshot.
            removing = operation == 'remove'
            if not removing and not config.get('GLOBAL_ALLSKY_MAP', {}).get('ENABLE', False):
                raise _Disabled('Disabled before queued publication executed')
            if removing:
                if identifier is None:
                    raise MapError('No installation registration identifier exists')
                data = {'machine_id': identifier, 'website_url': 'DELETE'}
            else:
                data = self._payload(config)
                if fingerprint(data) != payload_hash:
                    raise _MetadataChanged('Saved metadata changed; preview/update again')
                data['force'] = operation == 'force'
            def claim(state):
                if state.get('pending') != task.id or state.get('attempted_task') == task.id:
                    raise _AlreadyAttempted('Stale/already attempted task; no POST repeated')
                attempts = self._budget(state, operation == 'force', removing)
                attempts.append({'time': now, 'force': operation == 'force'})
                state.update(attempts=attempts[-16:], last_attempt=now, attempted_task=task.id,
                             last_status='Sending ' + operation)
            self._change(claim)  # Commits before network wait; no write transaction held.
            result = post(data, self.opener)
        except _AlreadyAttempted as exc:
            db.session.rollback()
            return {'ok': False, 'status': 'NOT_SENT', 'message': str(exc)}
        except (_MetadataChanged, _Disabled) as exc:
            db.session.rollback()
            result = {'ok': False, 'status': 'STALE' if isinstance(exc, _MetadataChanged) else 'DISABLED', 'message': str(exc)}
        except (MapError, ValueError) as exc:
            db.session.rollback()
            result = {'ok': False, 'status': 'FAILED', 'message': str(exc)}
        message = str(result.get('message') or result['status']).replace(identifier or '<none>', '[installation-id]')[:200]
        result['message'] = message
        def finish(state):
            if state.get('pending') == task.id:
                state.pop('pending', None)
            state['last_status'] = result['status'] + ': ' + message
            if 'maximum' in result:
                state['quota'] = {k: result[k] for k in ('updates', 'maximum') if k in result}
            if result['ok']:
                state['registered'] = operation != 'remove'
                state['needs_review'] = False
                if operation != 'remove':
                    state.update(last_success=now, payload_hash=payload_hash, auto_not_before=now + 300)
            elif result['status'] in ('STALE', 'DISABLED'):
                state['needs_review'] = False
            elif result['status'] == 'ALREADY_UPDATED':
                state['auto_not_before'] = now + QUOTA_SECONDS
            else:
                state['needs_review'] = True
        self._change(finish)
        if result['ok']:
            task.setSuccess('Global map ' + result['status'])
        else:
            task.setFailed('Global map ' + message)
        return result
