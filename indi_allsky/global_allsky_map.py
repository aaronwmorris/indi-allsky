"""Optional AllskyTeam map client. No capture code, image upload or host ID access."""
import hashlib
import html
import http.client
import ipaddress
import json
import logging
import math
import platform
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from urllib import error, parse, request

import psutil

from .version import __version__

ENDPOINT = 'https://www.thomasjacquin.com/allsky-map/postToMap.php'
ID_KEY = 'GLOBAL_MAP_ID'
STATE_KEY = 'GLOBAL_MAP_STATE'
RESPONSE_KEY = 'GLOBAL_MAP_RESPONSE'
ACTION = 'publishGlobalAllskyMap'
REFRESH_SECONDS = 48 * 3600
QUOTA_SECONDS = 24 * 3600
MIN_INTERVAL = 60
MAX_UPDATES = 5
TIMEOUT = 15
MAX_RESPONSE = 8192
MAX_DIAGNOSTIC_BODY = 2048

logger = logging.getLogger('indi_allsky')


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
    """URLs may use different hosts; a website still requires an image."""
    for index, value in enumerate((website, image)):
        if not isinstance(value, str):
            raise MapError('Public URLs must be text')
        if not value:
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
        policy_host = host.lower().rstrip('.')
        if index == 1 and (policy_host == 'allsky-map.com' or policy_host.endswith('.allsky-map.com')):
            raise MapError('allsky-map.com must not be used to host images for the Global Allsky Map')
        if policy_host == 'localhost' or policy_host.endswith('.local'):
            raise MapError('Public URLs must be reachable outside the local network')
        try:
            address = ipaddress.ip_address(policy_host)
        except ValueError:
            # Reject legacy numeric IPv4 spellings without DNS or platform parsing.
            # Canonical public IPv4/IPv6 literals remain handled by ipaddress.
            if re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)(?:\.(?:[0-9]+|0x[0-9a-f]+))*', policy_host):
                raise MapError('Use canonical public IP addresses in map URLs')
        else:
            if not address.is_global:
                raise MapError('Public URLs must not contain private/local IP addresses')
    if website and not image:
        raise MapError('Website URL requires an Image URL')


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


def _format_coordinate(value, latitude):
    """Plain decimal magnitude; never pad a source or expose float artefact digits."""
    text = format(abs(value), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    direction = ('N' if value >= 0 else 'S') if latitude else ('E' if value >= 0 else 'W')
    return text + direction


def publication_coordinates(latitude, longitude, private=False, accuracy='legacy'):
    """Saved location only; global privacy wins over any map-specific choice."""
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MapError('Invalid map coordinates') from exc
    if not (math.isfinite(latitude) and math.isfinite(longitude)) or abs(latitude) > 90 or abs(longitude) > 180:
        raise MapError('Map coordinates are outside their valid range')
    if private:
        return coordinate(latitude, True, True), coordinate(longitude, False, True)
    distances = {'0.5km': 500, '1km': 1000, '2km': 2000, '5km': 5000}
    if not isinstance(accuracy, str) or accuracy not in ('legacy', 'exact', *distances):
        raise MapError('Invalid Global Allsky Map location accuracy')
    if accuracy == 'legacy':
        return coordinate(latitude, True), coordinate(longitude, False)
    source = [Decimal(str(latitude)).normalize(), Decimal(str(longitude)).normalize()]
    if accuracy == 'exact':
        return _format_coordinate(source[0], True), _format_coordinate(source[1], False)

    # Finite row/ring grids: longitude spacing depends on the quantised row,
    # never on a finer, unpublished source latitude. R is an approximate sphere.
    radius, distance = 6371000, distances[accuracy]
    rows = math.ceil(math.pi * radius / distance)
    row = min(rows, max(0, math.floor((latitude + 90) * rows / 180 + 0.5)))
    lat = -90 + row * 180 / rows
    if row in (0, rows):
        lon = 0
    else:
        columns = max(1, math.ceil(2 * math.pi * radius * math.cos(math.radians(lat)) / distance))
        index = math.floor(((longitude + 180) % 360) * columns / 360 + 0.5) % columns
        lon = -180 + index * 360 / columns if columns > 1 else 0
    # Stored numeric values have no measurement-accuracy metadata. Conservatively
    # cap each axis at its own shortest-decimal precision (and at six places).
    result = []
    for value, original in zip((lat, lon), source):
        places = min(6, max(0, -original.as_tuple().exponent))
        result.append(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN))
    if abs(result[0]) == 90:
        result[1] = Decimal(0)
    elif result[1] == 180:
        result[1] = Decimal(-180)
    return _format_coordinate(result[0], True), _format_coordinate(result[1], False)


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


def canonical_version(version=None):
    """Map identity uses the dated application release, not package provenance."""
    value = __version__ if version is None else version
    match = re.fullmatch(r'(indi_v\d{4}\.\d{2}\.\d{2})(?:[+~.-].*)?', value)
    if not match:
        raise MapError('Cannot determine canonical INDI-AllSky application version')
    return match.group(1)


def _redact_response(text, identifier):
    if not identifier:
        return text
    text = re.sub(re.escape(identifier), '[installation-id]', text, flags=re.IGNORECASE)
    # Do not retain an echoed identifier hidden by common HTML/URL/JSON escaping.
    normalized = html.unescape(parse.unquote(text))
    normalized = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), normalized)
    if identifier.lower() in normalized.lower():
        return '[body withheld: encoded installation identifier]'
    return text


def website_url(config):
    """Read the integration-owned URL, retaining pre-PR saved-config compatibility."""
    return config.get('GLOBAL_ALLSKY_MAP', {}).get('WEBSITE_URL',
        config.get('WEBSITE', {}).get('PUBLIC_URL', ''))


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
    website = website_url(config)
    image = options.get('IMAGE_URL', '')
    validate_urls(website, image)
    private = bool(config.get('PRIVACY_MODE'))
    latitude, longitude = publication_coordinates(config.get('LOCATION_LATITUDE'),
        config.get('LOCATION_LONGITUDE'), private, options.get('LOCATION_ACCURACY', 'legacy'))
    equipment = str(options.get('EQUIPMENT', '') or '')
    return {
        'force': False, 'machine_id': identifier,
        'location': str(config.get('LOCATION_NAME', '') or ''),
        'owner': str(config.get('OWNER', '') or ''),
        'latitude': latitude, 'longitude': longitude,
        'website_url': website, 'image_url': image, 'camera': str(name),
        'lens': str(config.get('LENS_NAME', '') or ''),
        'computer': computer if computer is not None else computer_description(),
        'equipmentinfo': equipment,
        'allsky_version': canonical_version(), 'website_settings': {},
        'allsky_settings': {'equipmentinfo': equipment},
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


def post(data, opener=None, record=None):
    """One attempt; retain bounded, redacted evidence before protocol validation."""
    identifier = data.get('machine_id')
    req = request.Request(ENDPOINT, data=json.dumps(data).encode('utf-8'), method='POST', headers={
        'Accept': 'application/json', 'Content-Type': 'application/json',
        'User-Agent': 'indi-allsky/' + canonical_version(),
    })
    opener = opener or request.build_opener(_NoRedirect()).open

    def retain(evidence):
        if record:
            record(dict(evidence))

    def read_response(response, http_error=False):
        status = response.code if http_error else response.status
        content_type = getattr(response, 'headers', {}).get('Content-Type', '')
        evidence = {'http_status': status,
                    'content_type': _redact_response(content_type, identifier)[:256],
                    'body': '', 'body_truncated': False, 'bytes_read': 0,
                    'outcome': 'awaiting_body'}
        retain(evidence)  # Even a subsequent read failure retains status/content type.
        try:
            body = response.read(MAX_RESPONSE + 1) or b''
        except (OSError, http.client.HTTPException) as exc:
            evidence.update(outcome='transport_ambiguous', body_read_failed=True)
            retain(evidence)
            raise MapError('Response read failed; outcome may be unknown. No retry was made.') from exc
        text = body.decode('utf-8', errors='replace')
        redacted = _redact_response(text, identifier).encode('utf-8')
        evidence.update(body=redacted[:MAX_DIAGNOSTIC_BODY].decode('utf-8', errors='replace'),
                        body_truncated=len(body) > MAX_DIAGNOSTIC_BODY or len(redacted) > MAX_DIAGNOSTIC_BODY,
                        bytes_read=len(body), response_limit_exceeded=len(body) > MAX_RESPONSE,
                        outcome='unparsed')
        retain(evidence)
        if http_error or status != 200:
            evidence['outcome'] = 'http_error'
            retain(evidence)
            raise MapError('Map HTTP error {0}'.format(status))
        try:
            if len(body) > MAX_RESPONSE:
                raise MapError('Map response exceeds the size limit')
            result = parse_response(text, data.get('website_url') == 'DELETE')
        except MapError as exc:
            evidence.update(outcome='protocol_ambiguous', protocol_error=str(exc))
            retain(evidence)  # Durable before the failure is recorded by the worker.
            raise
        result['message'] = _redact_response(result['message'], identifier)
        result['messages'] = [_redact_response(m, identifier) for m in result['messages']]
        evidence.update(outcome='success' if result['ok'] else 'server_result',
                        terminal_result={k: result[k] for k in ('status', 'ok', 'updates', 'maximum') if k in result})
        retain(evidence)
        return result

    try:
        response = opener(req, timeout=TIMEOUT)
    except error.HTTPError as exc:
        with exc:
            return read_response(exc, http_error=True)
    except (error.URLError, OSError, http.client.HTTPException) as exc:
        retain({'http_status': None, 'content_type': None, 'body': '',
                'body_truncated': False, 'bytes_read': 0, 'outcome': 'transport_ambiguous'})
        raise MapError('Transport failed or timed out; outcome may be unknown. No retry was made.') from exc
    with response:
        return read_response(response)


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
            try:
                state = json.loads(old)
                if not isinstance(state, dict):
                    raise ValueError('not an object')
            except (TypeError, ValueError) as exc:
                db.session.rollback()
                raise MapError('Stored map state is invalid; refusing to replace it') from exc
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

    def suppress_publication(self):
        """Explicit withdrawal survives unrelated stale whole-config write-backs."""
        self._change(lambda state: state.update(publication_suppressed=True))

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
        public = {k: state.get(k) for k in ('registered', 'pending', 'last_status', 'last_success', 'last_attempt', 'needs_review', 'quota', 'publication_suppressed')}
        if state.get('publication_suppressed'):
            public['publication_notice'] = 'Publication suppressed; enable, Preview and explicitly Register to resume'
        pending = state.get('pending')
        if pending and state.get('attempted_task') == pending:
            from .flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueState
            task = IndiAllSkyDbTaskQueueTable.query.filter_by(id=pending).first()
            if not task or task.state in (TaskQueueState.EXPIRED, TaskQueueState.FAILED):
                public['needs_review'] = True
                public['last_status'] = 'Interrupted request; manual review required, not retried'
        latest_response = self._read(RESPONSE_KEY)
        if latest_response:
            try:
                evidence = json.loads(latest_response)
                if not isinstance(evidence, dict):
                    raise ValueError('not an object')
            except ValueError:
                public['response_evidence_error'] = 'Stored response evidence is invalid'
            else:
                public['response_evidence'] = evidence
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
        if not removing and not force and sum(not a['force'] for a in attempts) >= MAX_UPDATES:
            raise MapError('Five ordinary attempts in the last 24 hours; wait for quota or explicitly force an update')
        if not removing and now - state.get('last_attempt', -QUOTA_SECONDS) < MIN_INTERVAL:
            raise MapError('Wait one minute between map requests')
        return attempts

    def enqueue(self, operation, preview_token=None, automatic=False):
        from .flask import db
        from .flask.models import IndiAllSkyDbTaskQueueTable, TaskQueueState, TaskQueueQueue
        if operation not in ('register', 'update', 'force', 'remove') or (automatic and operation != 'update'):
            raise MapError('Invalid map operation')
        if operation == 'remove':
            self.suppress_publication()
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
            if state.get('publication_suppressed') and operation != 'remove':
                if automatic:
                    return None
                if operation != 'register':
                    raise MapError('Publication suppressed; Preview and explicitly Register to resume')
            if automatic and (not state.get('registered') or state.get('needs_review')):
                return None
            if operation == 'remove' and not state.get('registered') and str(state.get('last_status', '')).startswith('DELETED'):
                raise MapError('The map entry was already removed')
            pending = state.get('pending')
            if pending:
                task = db.session.get(IndiAllSkyDbTaskQueueTable, pending)
                if task and task.state in (TaskQueueState.MANUAL, TaskQueueState.QUEUED, TaskQueueState.RUNNING):
                    if state.get('publication_suppressed') and operation == 'register':
                        raise MapError('Publication suppressed; wait for the pending request to finish')
                    if operation == 'remove' and task.data['kwargs']['operation'] != 'remove':
                        if state.get('attempted_task') == pending:
                            raise MapError('Disabled; publication is in progress. Retry removal after it finishes.')
                        task.state = TaskQueueState.EXPIRED
                    else:
                        intent = task.data['kwargs']
                        if not automatic and (intent['operation'] != operation or intent.get('payload_hash') != digest):
                            raise MapError('A different map request is pending; wait for it to finish')
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
            if operation == 'register' and not automatic:
                state['publication_suppressed'] = False
            state['last_status'] = 'Queued ' + operation
            return job.id
        return self._change(queue)

    def schedule(self):
        config = self.config()
        if not config.get('GLOBAL_ALLSKY_MAP', {}).get('ENABLE', False):
            return None
        state = self.state()
        if state.get('publication_suppressed') or not state.get('registered') or state.get('needs_review'):
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
                if not removing and state.get('publication_suppressed'):
                    raise _Disabled('Publication suppressed before queued publication executed')
                attempts = self._budget(state, operation == 'force', removing)
                if not removing:
                    attempts.append({'time': now, 'force': operation == 'force'})
                state.update(attempts=attempts[-16:], last_attempt=now, attempted_task=task.id,
                             last_status='Sending ' + operation)
            self._change(claim)  # Commits before network wait; no write transaction held.
            def record_response(evidence):
                # Keep per-task history and the latest response beyond routine task cleanup.
                # The separate state row has a 4096-character JSON budget, including escapes.
                from .flask.models import IndiAllSkyDbStateTable
                stored = dict(evidence, task_id=task.id)
                value = json.dumps(stored)
                while len(value) > 4096:
                    if not stored['body']:
                        raise MapError('Map diagnostic metadata exceeds storage limit')
                    stored['body'] = stored['body'][:len(stored['body']) // 2]
                    stored['body_truncated'] = True
                    value = json.dumps(stored)
                self._ensure(RESPONSE_KEY, '{}')
                IndiAllSkyDbStateTable.query.filter_by(key=RESPONSE_KEY).update(
                    {'value': value}, synchronize_session=False)
                task.data = dict(task.data, response_evidence=stored)
                db.session.commit()
            result = post(data, self.opener, record=record_response)
        except _AlreadyAttempted as exc:
            from .flask.models import TaskQueueState
            db.session.rollback()
            if task.state in (TaskQueueState.MANUAL, TaskQueueState.QUEUED, TaskQueueState.RUNNING):
                task.setFailed('Global map task no longer owns an unattempted request')
            return {'ok': False, 'status': 'NOT_SENT', 'message': str(exc)}
        except (_MetadataChanged, _Disabled) as exc:
            db.session.rollback()
            result = {'ok': False, 'status': 'STALE' if isinstance(exc, _MetadataChanged) else 'DISABLED', 'message': str(exc)}
        except (MapError, ValueError) as exc:
            db.session.rollback()
            result = {'ok': False, 'status': 'FAILED', 'message': str(exc)}
        except Exception as exc:
            db.session.rollback()
            logger.error('Global Allsky Map execution failed (%s)', type(exc).__name__)
            result = {'ok': False, 'status': 'FAILED', 'message': 'Unexpected map failure; inspect task status before retrying'}
        message = str(result.get('message') or result['status']).replace(identifier or '<none>', '[installation-id]')[:200]
        result['message'] = message
        def finish(state):
            if state.get('pending') != task.id:
                return  # A superseded task must not alter its replacement's state.
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
                pass  # No request sent; preserve any earlier unresolved review.
            elif result['status'] == 'ALREADY_UPDATED':
                state['auto_not_before'] = now + QUOTA_SECONDS
            else:
                # Before a durable claim no POST was made; retain any earlier review.
                state['needs_review'] = (state.get('attempted_task') == task.id
                                         or bool(state.get('needs_review')))
        self._change(finish)
        if result['ok']:
            task.setSuccess('Global map ' + result['status'])
        else:
            task.setFailed('Global map ' + message)
        return result
