"""Optional availability scheduling for finite archive runs.

Only the main service calls tick(). Browser requests save settings/read status;
the probe thread owns no Flask context, database session or upload queue.
Preferences live in the normal SYNCAPI configuration. Only progress and pause
controls are local state, so exporting a config does not export a running job.
Revision tokens invalidate stale probes/jobs when preferences change or pause.
"""

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import logging
import math
from threading import Thread
import time
from uuid import uuid4

from .syncapi import archive_sync_enabled
from . import syncapi_sync as sync


logger = logging.getLogger('indi_allsky')
CONTROL_KEY = 'SYNCAPI_SCHEDULE_CONTROL'
STATUS_KEY = 'SYNCAPI_SCHEDULE_STATUS'
APPLYING_MESSAGE = 'Schedule saved. Waiting for indi-allsky to apply the configuration.'


def configured_settings(config):
    options = config.get('SYNCAPI', {})
    if not isinstance(options, dict):
        raise ValueError('Invalid SyncAPI configuration.')
    return validate_settings(dict(
        enabled=options.get('ARCHIVE_SCHEDULE', False),
        interval=options.get('ARCHIVE_INTERVAL', 10),
        delay=options.get('ARCHIVE_DELAY', 0),
        upload_limit=options.get('ARCHIVE_UPLOAD_LIMIT', 0),
        types=options.get('ARCHIVE_TYPES', list(sync.DEFAULT_TYPES)),
    ))


def settings(config=None):
    if config is None:
        row = sync.models.IndiAllSkyDbConfigTable.query.order_by(sync.models.IndiAllSkyDbConfigTable.createDate.desc()).first()
        config = row.data if row else {}
    options = configured_settings(config)
    fingerprint = settings_fingerprint(options)
    control = sync.get_state(CONTROL_KEY, {})
    # Restoring different preferences invalidates old jobs/probes as well as
    # pauses. Unrelated config edits must not invalidate a running sync.
    options['revision'] = fingerprint + control.get('revision', '')
    if options['enabled'] and control.get('paused_settings') == fingerprint:
        options.update(enabled=False, paused_reason=control['paused_reason'])
    return options


def settings_fingerprint(options):
    return hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()


def validate_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid synchronization schedule.')
    enabled, interval, delay = (payload.get(key) for key in ('enabled', 'interval', 'delay'))
    types = payload.get('types')
    if type(enabled) is not bool:
        raise ValueError('Choose whether automatic synchronization is enabled.')
    if type(interval) is not int or not 1 <= interval <= 1440:
        raise ValueError('Check interval must be between 1 and 1440 minutes.')
    if type(delay) is not int or not 0 <= delay <= 1440:
        raise ValueError('Startup delay must be between 0 and 1440 minutes.')
    if not isinstance(types, list) or not types or any(not isinstance(t, str) or t not in sync.MEDIA for t in types):
        raise ValueError('Select at least one supported media type.')
    upload_limit = sync.validate_upload_limit(payload.get('upload_limit'))
    return dict(enabled=enabled, interval=interval, delay=delay, upload_limit=upload_limit,
                types=list(dict.fromkeys(types)))


def save_settings(config, payload):
    """Stage preferences and resume controls for the normal config transaction."""
    options = validate_settings(payload)
    current = configured_settings(config)
    paused = settings(config).get('paused_reason')
    # General configuration saves also submit unchanged schedule fields. Do not
    # restart the timer or invalidate an active worker for an unrelated edit.
    changed = current != options or bool(paused and options['enabled'])
    if changed and sync.active_task():
        raise ValueError('Cancel the running synchronization before changing its schedule.')
    # Keep the preference when SyncAPI is off or in automatic-upload mode.
    # The scheduler already requires an applied Archive sync configuration.
    if changed and options['enabled'] and archive_sync_enabled(config):
        sync.validate_destination(config)
    keys = dict(enabled='SCHEDULE', interval='INTERVAL', delay='DELAY',
                upload_limit='UPLOAD_LIMIT', types='TYPES')
    config.setdefault('SYNCAPI', {}).update({'ARCHIVE_' + keys[key]: value for key, value in options.items()})
    # Do not commit here: a failed config save must also leave the pause intact.
    if changed:
        sync.set_state(CONTROL_KEY, dict(revision=str(uuid4())), commit=False)
    return changed


def pause(message):
    options = settings()
    if options['enabled']:
        options.pop('revision')
        sync.set_state(CONTROL_KEY, dict(revision=str(uuid4()),
                       paused_settings=settings_fingerprint(options), paused_reason=message))


def status():
    options = settings()
    state = sync.get_state(STATUS_KEY, {})
    if not options['enabled']:
        state = dict(state='paused' if options.get('paused_reason') else 'disabled',
                     message=options.get('paused_reason', 'Automatic synchronization is disabled.'))
    elif state.get('revision') != options['revision']:
        state = dict(state='applying', message=APPLYING_MESSAGE)
    return dict(settings=options, **state)


def has_pending(types):
    # Use the worker's exact eligibility rules, with an existence query instead
    # of counting/scanning the archive. Empty cycles create no tasks or uploads.
    worker = sync.SyncApiSyncWorker(None, None)
    cutoff = datetime.now() - timedelta(minutes=10)
    return any(worker.candidate_query(sync.MEDIA[name][0], None, cutoff)
               .with_entities(sync.MEDIA[name][0].id).first() is not None for name in types)


def probe_receiver(config, camera_id, camera_uuid):
    from .filetransfer.requests_syncapi_v1 import requests_syncapi_v1
    from .filetransfer.exceptions import ConnectionFailure, CertificateValidationFailure, AuthenticationFailure, TransferFailure

    client = requests_syncapi_v1(config, quiet=True)
    try:
        options = config['SYNCAPI']
        timeouts = [float(options.get('CONNECT_TIMEOUT', 10)), float(options.get('TIMEOUT', 60))]
        if any(not math.isfinite(t) or t <= 0 for t in timeouts):
            raise ValueError('Invalid SyncAPI timeout.')
        client.connect_timeout, client.timeout = min(timeouts[0], 5), min(timeouts[1], 10)
        client.connect(hostname=options['BASEURL'].rstrip('/') + '/sync/v1/camera',
                       username=options['USERNAME'], apikey=options['APIKEY'],
                       cert_bypass=options.get('CERT_BYPASS', False))
        # A signed camera lookup proves authentication/database readiness even
        # before the camera exists; the first actual run registers it.
        client.put(local_file='camera', empty_file=True, lookup=True, availability_probe=True,
                   metadata={'id': camera_id or 0, 'camera_uuid': camera_uuid})
        return 'ready', 'Receiver is available.'
    except ConnectionFailure:
        return 'offline', 'Receiver unavailable. Waiting for the next check.'
    except CertificateValidationFailure:
        return 'blocked', 'Receiver certificate validation failed. Check the certificate setting, then enable the schedule again.'
    except AuthenticationFailure:
        return 'blocked', 'Receiver authentication failed. Check the account and API key, then enable the schedule again.'
    except (TransferFailure, ValueError, KeyError):
        return 'blocked', 'Receiver readiness could not be verified. Check the SyncAPI URL and settings, then enable the schedule again.'
    except Exception:
        logger.debug('SyncAPI availability check failed', exc_info=True)
        return 'blocked', 'Availability check failed unexpectedly. Details are available at debug log level. Enable the schedule again after correcting the problem.'
    finally:
        client.close()


class ReceiverProbe(Thread):
    def __init__(self, config, camera_id, camera_uuid):
        # DNS can outlive socket timeouts. Keep at most one probe, and never
        # make capture/shutdown wait for the resolver or the remote server.
        super().__init__(name='SyncAPI-availability', daemon=True)
        self.args = deepcopy(config), camera_id, camera_uuid
        self.result = None

    def run(self):
        self.result = probe_receiver(*self.args)


class SyncApiScheduler:
    def __init__(self):
        self.signature = None
        self.phase = 'disabled'
        self.deadline = 0
        self.probe = None
        self.probe_stale = False
        self.task_id = None

    def publish(self, options, state, message, delay=None):
        value = dict(revision=options['revision'], state=state, message=message)
        if delay is not None:
            value['next_action'] = (datetime.now().astimezone() + timedelta(seconds=delay)).isoformat(timespec='seconds')
        if sync.get_state(STATUS_KEY) != value:
            sync.set_state(STATUS_KEY, value)

    def wait(self, options, message):
        self.phase = 'waiting'
        self.deadline = time.monotonic() + options['interval'] * 60
        self.publish(options, 'waiting', message, options['interval'] * 60)

    def block(self, message, log=True):
        pause(message)
        if log:
            logger.warning('Automatic SyncAPI synchronization paused: %s', message)

    def tick(self, config, config_id, busy=False):
        # Match IndiAllSkyConfig's ordering, including after clock corrections.
        latest = sync.models.IndiAllSkyDbConfigTable.query.order_by(sync.models.IndiAllSkyDbConfigTable.createDate.desc()).first()
        options = settings(latest.data if latest else config)
        applied = latest is not None and latest.id == config_id
        enabled = options['enabled'] and archive_sync_enabled(config) and applied
        signature = options['revision'], config_id, enabled
        if signature != self.signature:
            self.signature = signature
            self.probe_stale = True
            self.task_id = None
            self.wait(options, 'Waiting for the next availability check.')
        if not enabled:
            # A saved configuration can be waiting for the service's next
            # reload. Do not ask users to save the same settings again.
            if options['enabled'] and not applied:
                self.publish(options, 'applying', APPLYING_MESSAGE)
            else:
                self.publish(options, 'disabled', 'Save and apply Archive sync mode to use the schedule.')
            return

        task = sync.active_task()
        if busy or task:
            self.probe_stale = True
            self.phase = 'running'
            if task:
                self.task_id = task.id
            self.publish(options, 'running', 'Synchronization is running; availability checks are suspended.')
            return
        if self.phase == 'running':
            result = sync.get_state(sync.STATUS_KEY, {})
            if result.get('task_id') == self.task_id and result.get('state') == 'failed' and result.get('reason') != 'connection':
                self.block(result.get('message', 'Synchronization failed.') + ' Enable the schedule again after correcting the problem.', log=False)
                return
            self.wait(options, 'Run finished. Waiting for the next availability check.')

        if self.probe:
            if self.probe.is_alive():
                return
            result = self.probe.result
            self.probe = None
            if self.probe_stale:
                return
            outcome, message = result or ('blocked', 'Availability check stopped unexpectedly.')
            if outcome == 'offline':
                self.wait(options, message)
            elif outcome == 'blocked':
                self.block(message)
            elif self.phase == 'checking' and options['delay']:
                self.phase = 'settling'
                self.deadline = time.monotonic() + options['delay'] * 60
                self.publish(options, 'settling', 'Receiver is available. Waiting for the startup delay.', options['delay'] * 60)
            else:
                self.start_run(config, options)
            return

        if time.monotonic() < self.deadline:
            return
        if not has_pending(options['types']):
            self.wait(options, 'No eligible files are pending. Waiting for the next check.')
            return
        try:
            sync.validate_destination(config)
        except ValueError as exc:
            self.block(str(exc))
            return
        camera = sync.models.IndiAllSkyDbCameraTable.query.filter_by(local=True, hidden=False).order_by(
            sync.models.IndiAllSkyDbCameraTable.sync_id.is_(None), sync.models.IndiAllSkyDbCameraTable.id).first()
        if camera is None:
            self.wait(options, 'Waiting for a local camera.')
            return
        self.phase = 'checking_ready' if self.phase == 'settling' else 'checking'
        self.publish(options, self.phase, 'Checking the receiver with the saved SyncAPI credentials.')
        self.probe = ReceiverProbe(config, camera.sync_id, camera.uuid)
        self.probe_stale = False
        # Release the read transaction before network activity, including MySQL.
        sync.db.session.commit()
        self.probe.start()

    def start_run(self, config, options):
        # A browser command may have changed the schedule during the probe.
        # The worker checks this revision too, closing the admission race.
        if settings()['revision'] != options['revision']:
            return
        if not has_pending(options['types']):
            self.wait(options, 'No eligible files are pending. Waiting for the next check.')
            return
        try:
            task = sync.request_sync(config, options['types'], schedule_revision=options['revision'],
                                     upload_limit=options['upload_limit'])
        except ValueError as exc:
            self.block(str(exc))
            return
        self.task_id = task.id
        self.phase = 'running'
        self.publish(options, 'running', 'Synchronization is queued.')
