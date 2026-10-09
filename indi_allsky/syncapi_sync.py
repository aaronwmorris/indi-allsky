"""Finite, explicitly requested SyncAPI archive runs.

The main service admits one worker at a time. Database state is for local UI
progress and cancellation; per-asset sync_id values are the durable checkpoints.
Polling status does not start transfers. An explicitly enabled availability
schedule can request new runs, including after a service restart.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import hashlib
import heapq
import logging
import math
from threading import Event, Thread
import time

from sqlalchemy import and_, or_, func

from . import constants
from .flask import db
from .flask import models
from .syncapi import destination_fingerprint, archive_sync_enabled


logger = logging.getLogger('indi_allsky')
TASK_ACTION = 'archive_sync'
STATUS_KEY = 'SYNCAPI_RUN'
CANCEL_KEY = 'SYNCAPI_CANCEL'
DESTINATION_KEY = 'SYNCAPI_DESTINATION'
ACTIVE_STATES = (models.TaskQueueState.MANUAL, models.TaskQueueState.QUEUED, models.TaskQueueState.RUNNING)
MEDIA = {
    'image': (models.IndiAllSkyDbImageTable, constants.IMAGE, 'Images'),
    'panoramaimage': (models.IndiAllSkyDbPanoramaImageTable, constants.PANORAMA_IMAGE, 'Panorama images'),
    'video': (models.IndiAllSkyDbVideoTable, constants.VIDEO, 'Timelapses'),
    'minivideo': (models.IndiAllSkyDbMiniVideoTable, constants.MINI_VIDEO, 'Mini timelapses'),
    'keogram': (models.IndiAllSkyDbKeogramTable, constants.KEOGRAM, 'Keograms'),
    'startrail': (models.IndiAllSkyDbStarTrailsTable, constants.STARTRAIL, 'Star trails'),
    'startrailvideo': (models.IndiAllSkyDbStarTrailsVideoTable, constants.STARTRAIL_VIDEO, 'Star-trail videos'),
    'panoramavideo': (models.IndiAllSkyDbPanoramaVideoTable, constants.PANORAMA_VIDEO, 'Panorama videos'),
    'rawimage': (models.IndiAllSkyDbRawImageTable, constants.RAW_IMAGE, 'RAW files'),
    'fitsimage': (models.IndiAllSkyDbFitsImageTable, constants.FITS_IMAGE, 'FITS files'),
}
# RAW and FITS archives are opt-in regardless of where new types are added.
DEFAULT_TYPES = [name for name in MEDIA if name not in ('rawimage', 'fitsimage')]


def get_state(key, default=None):
    # Flask requests and the worker use separate sessions. Refresh cached rows
    # so cancellation and progress changes from another session are visible.
    row = db.session.get(models.IndiAllSkyDbStateTable, key, populate_existing=True)
    return json.loads(row.value) if row else default


def set_state(key, value, commit=True):
    """Save local state; configuration saves may include it in their transaction."""
    row = db.session.get(models.IndiAllSkyDbStateTable, key)
    if row is None:
        row = models.IndiAllSkyDbStateTable(key=key)
        db.session.add(row)
    row.value = json.dumps(value)
    row.createDate = datetime.now()
    if commit:
        db.session.commit()


def validate_destination(config, previous=None):
    # Media tables have only one sync_id each, not a checkpoint per destination.
    fingerprint = destination_fingerprint(config)
    bound = get_state(DESTINATION_KEY)
    if not bound and previous and previous.get('SYNCAPI', {}).get('ENABLE'):
        bound = destination_fingerprint(previous)
    if bound and bound != fingerprint:
        raise ValueError('The SyncAPI destination changed. Existing transfer records belong to the previous server; restore its URL/account before syncing.')
    return fingerprint


def active_task():
    return models.IndiAllSkyDbTaskQueueTable.query.filter(
        models.IndiAllSkyDbTaskQueueTable.queue == models.TaskQueueQueue.MAIN,
        models.IndiAllSkyDbTaskQueueTable.state.in_(ACTIVE_STATES),
        models.IndiAllSkyDbTaskQueueTable.data['action'].as_string() == TASK_ACTION,
    ).order_by(models.IndiAllSkyDbTaskQueueTable.id).first()


def status():
    result = get_state(STATUS_KEY, {'state': 'idle', 'message': 'No archive synchronization has run yet.'})
    task = active_task()
    if task and result.get('task_id') != task.id:
        result = {'task_id': task.id, 'state': 'queued', 'message': 'Waiting for the indi-allsky service.'}
    result['active'] = task is not None
    if task:
        result['scheduled'] = task.data.get('schedule_revision') is not None
    result['cancel_requested'] = bool(task and get_state(CANCEL_KEY, 0) >= task.id)
    # A blocked socket may prevent worker updates. Do not present an old
    # transfer rate as current speed while waiting for the next update.
    if result.get('rates') and datetime.now() - datetime.fromisoformat(result['updated']) > timedelta(seconds=15):
        result.pop('rates')
    return result


def validate_upload_limit(value):
    if type(value) is not int or value not in (0, 128, 256, 512, 1024, 2048, 5120, 10240):
        raise ValueError('Choose a supported upload speed limit.')
    return value


def request_sync(config, types, schedule_revision=None, upload_limit=None):
    if not archive_sync_enabled(config):
        raise ValueError('Save and apply Archive sync mode before starting a synchronization.')
    if not isinstance(types, list) or not types or any(not isinstance(t, str) or t not in MEDIA for t in types):
        raise ValueError('Select at least one supported media type.')
    if upload_limit is None:
        from .syncapi_schedule import settings
        upload_limit = settings(config)['upload_limit']
    upload_limit = validate_upload_limit(upload_limit)
    fingerprint = validate_destination(config)
    # This check avoids ordinary duplicate clicks. The main service's
    # _queueManualTasks() is the final admission gate for concurrent requests.
    task = active_task()
    if task:
        return task
    set_state(DESTINATION_KEY, fingerprint)
    task = models.IndiAllSkyDbTaskQueueTable(
        queue=models.TaskQueueQueue.MAIN, state=models.TaskQueueState.MANUAL, priority=100,
        data={'action': TASK_ACTION, 'types': list(dict.fromkeys(types)), 'destination': fingerprint,
              'upload_limit': upload_limit},
    )
    if schedule_revision is not None:
        task.data['schedule_revision'] = schedule_revision
    db.session.add(task)
    db.session.commit()
    return task


def cancel_sync(task_id):
    task = active_task()
    if task and task.id == task_id:
        # The stored task origin is authoritative, even if the browser's
        # schedule checkbox has been edited since this run started.
        if task.data.get('schedule_revision') is not None:
            from .syncapi_schedule import pause
            pause('Scheduled synchronization cancelled. Enable and save the schedule to resume.')
        # Include duplicate clicks queued before cancellation, but not a future run.
        latest = db.session.query(func.max(models.IndiAllSkyDbTaskQueueTable.id)).scalar() or task.id
        set_state(CANCEL_KEY, latest)


def interrupt_previous_run():
    result = get_state(STATUS_KEY)
    if result and result.get('state') in ('running', 'queued'):
        result.update(state='interrupted', message='Service restarted. Press Sync now to continue.', finished=datetime.now().isoformat())
        set_state(STATUS_KEY, result)


def metadata_for(entry, media_type, parent=None):
    """Keep portable columns/custom data; never send sender-local identifiers."""
    excluded = {'id', 'camera_id', 'filename', 'sync_id', 'uploaded', 'local', 'data'}
    if media_type == constants.CAMERA:
        excluded.update(('createDate', 'connectDate'))
    metadata = {}
    for column in entry.__table__.columns:
        if column.name in excluded or column.name.startswith('createDate_'):
            continue
        value = getattr(entry, column.name)
        if isinstance(value, datetime):
            value = value.timestamp()
        elif isinstance(value, date):
            value = value.strftime('%Y%m%d')
        metadata[column.name] = deepcopy(value)
    metadata['type'] = media_type
    metadata['data'] = deepcopy(entry.data or {})
    if media_type == constants.CAMERA:
        return metadata
    metadata['camera_uuid'] = entry.camera.uuid
    metadata['utc_offset'] = entry.createDate.astimezone().utcoffset().total_seconds()
    if media_type == constants.THUMBNAIL:
        metadata.update(origin=parent['type'], night=parent['night'], dayDate=parent['dayDate'])
    if media_type == constants.IMAGE:
        sample = models.IndiAllSkyDbLongTermKeogramTable.query.filter_by(
            camera_id=entry.camera_id, ts=int(entry.createDate.timestamp()),
        ).first()
        metadata['keogram_pixels'] = (
            [[getattr(sample, c + str(i)) for c in ('r', 'g', 'b')] for i in range(1, 6)]
            if sample else None
        )
    return metadata


class SyncStopped(Exception):
    pass


class SyncApiSyncWorker(Thread):
    """One finite archive pass with a separate Flask/database session."""
    page_size = 100
    retry_delays = (5, 15)

    def __init__(self, app, task_id):
        super().__init__(name='SyncAPI-archive')
        self.app = app
        self.task_id = task_id
        # None identifies a manual run, even while the availability schedule is
        # enabled. Scheduled runs carry the saved revision in their task data.
        self.schedule_revision = None
        self.stop_event = Event()
        self.progress = {}
        self.last_progress = 0
        self.upload_limit = 0
        self.transferred_bytes = 0
        self.rate_sample = None

    def stop(self):
        self.stop_event.set()

    def run(self):
        with self.app.app_context():
            self.execute()

    def check_control(self):
        # End read transactions before waiting on the network, including on MySQL.
        db.session.commit()
        if self.stop_event.is_set() or get_state(CANCEL_KEY, 0) >= self.task_id:
            raise SyncStopped('Synchronization cancelled. Press Sync now to continue.')
        if self.schedule_revision is not None:
            from .syncapi_schedule import settings
            schedule = settings()
            if not schedule['enabled'] or schedule['revision'] != self.schedule_revision:
                raise SyncStopped('Automatic synchronization paused or its settings changed.')
        latest = models.IndiAllSkyDbConfigTable.query.order_by(models.IndiAllSkyDbConfigTable.createDate.desc()).first()
        config = latest.data if latest else self.config
        if not archive_sync_enabled(config) or destination_fingerprint(config) != self.destination:
            raise SyncStopped('SyncAPI configuration changed. Press Sync now after applying the desired settings.')
        db.session.commit()

    def publish(self, force=False):
        now = time.monotonic()
        if force or now - self.last_progress >= 5:
            sample = (now, self.transferred_bytes, self.progress['completed'], self.progress['files'])
            if self.rate_sample is None:
                self.rate_sample = sample
            elif now - self.rate_sample[0] >= 1:
                # Use the elapsed sampling interval, including lookup/retry
                # waits. Ignore sub-second forced updates to avoid spikes.
                elapsed = now - self.rate_sample[0]
                self.progress['rates'] = {key: (sample[i] - self.rate_sample[i]) / elapsed
                                          for i, key in enumerate(('bytes', 'items', 'files'), 1)}
                self.rate_sample = sample
            if self.progress['state'] != 'running':
                self.progress.pop('rates', None)
            self.progress['updated'] = datetime.now().isoformat()
            set_state(STATUS_KEY, self.progress)
            self.last_progress = now

    def candidate_query(self, model, maximum, cutoff):
        # A parent can be acknowledged while its thumbnail still needs repair.
        thumbnail = models.IndiAllSkyDbThumbnailTable
        missing_thumbnail = db.session.query(thumbnail.id).filter(
            thumbnail.uuid == model.thumbnail_uuid, thumbnail.sync_id.is_(None),
        ).exists()
        query = model.query.join(model.camera).filter(
            models.IndiAllSkyDbCameraTable.local.is_(True),
            models.IndiAllSkyDbCameraTable.hidden.is_(False),
            model.createDate <= cutoff,
            or_(model.sync_id.is_(None), missing_thumbnail),
        )
        if maximum is not None:
            query = query.filter(model.id <= maximum)
        if hasattr(model, 'success'):
            query = query.filter(model.success.is_(True))
        return query

    def candidate_entries(self, name, maximum, cutoff):
        """Yield a bounded page at a time for merging media types by date."""
        model = MEDIA[name][0]
        cursor = None
        while True:
            self.check_control()
            query = self.candidate_query(model, maximum, cutoff)
            if cursor:
                # Offset pagination would skip rows as successful uploads leave
                # this query. Use the last date/ID, including skipped files.
                query = query.filter(or_(model.createDate > cursor[0], and_(model.createDate == cursor[0], model.id > cursor[1])))
            ids = query.with_entities(model.id, model.createDate).order_by(model.createDate, model.id).limit(self.page_size).all()
            if not ids:
                return
            for entry_id, created in ids:
                cursor = (created, entry_id)
                yield created, name, entry_id

    def transfer(self, entry, metadata):
        from .filetransfer.exceptions import ConnectionFailure

        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            try:
                # Reopen the media and repeat the lookup: a failed reply can
                # follow a successful receiver commit. Never replay a used stream.
                return self.transfer_once(entry, metadata)
            except ConnectionFailure as exc:
                if attempt == attempts - 1:
                    raise ConnectionFailure('Synchronization stopped after {0:d} attempts. {1}'.format(attempts, exc)) from exc
                delay = self.retry_delays[attempt]
                self.progress['message'] = '{0}. Retrying in {1:d} seconds (attempt {2:d} of {3:d}).'.format(exc, delay, attempt + 2, attempts)
                self.publish(force=True)
                self.wait_for_retry(delay)
                self.progress['message'] = 'Synchronization running.'
                self.publish(force=True)

    def wait_for_retry(self, delay):
        # Poll the database cancellation flag without holding a read transaction;
        # the event also wakes immediately when the service asks us to stop.
        for _ in range(delay):
            self.check_control()
            self.stop_event.wait(1)
        self.check_control()

    def upload_progress(self, transferred, total):
        # These bytes have been read for the request, not acknowledged by the
        # receiver. Keep them separate from completed totals and reset per try.
        # The speed counter spans attempts, so retries count as traffic without
        # adding them to the acknowledged file/byte totals.
        self.transferred_bytes += transferred - self.progress['upload']['bytes']
        self.progress['upload'].update(bytes=transferred, total=total)
        if self.stop_event.is_set() or time.monotonic() - self.last_progress >= 5:
            self.check_control()
            self.publish()

    def transfer_once(self, entry, metadata):
        # Keep optional transfer backends out of the web/status import path.
        from .filetransfer.requests_syncapi_v1 import requests_syncapi_v1
        from .filetransfer.exceptions import ConnectionFailure, TransferFailure

        self.check_control()
        settings = self.config['SYNCAPI']
        path = entry.getFilesystemPath()
        client = requests_syncapi_v1(self.config, quiet=True)
        client.connect_timeout = float(settings.get('CONNECT_TIMEOUT', 10))
        client.timeout = float(settings.get('TIMEOUT', 60))
        if any(not math.isfinite(t) or t <= 0 for t in (client.connect_timeout, client.timeout)):
            raise ValueError('SyncAPI timeouts must be finite positive numbers.')
        stage = 'Connection'
        try:
            client.connect(hostname=settings['BASEURL'].rstrip('/') + '/' + constants.ENDPOINT_V1[metadata['type']],
                           username=settings['USERNAME'], apikey=settings['APIKEY'],
                           cert_bypass=settings.get('CERT_BYPASS', False))
            if metadata['type'] != constants.CAMERA:
                # Recover a lost acknowledgement by verifying the remote bytes
                # before sending the file again. A timestamp alone is not proof.
                digest = hashlib.sha256()
                with path.open('rb') as source:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        if self.stop_event.is_set():
                            raise SyncStopped('Synchronization cancelled. Press Sync now to continue.')
                        # UI cancellation lives in the database, not stop_event.
                        # Check it while hashing large files without querying
                        # once per block on fast disks; keep status fresh too.
                        if time.monotonic() - self.last_progress >= 5:
                            self.check_control()
                            self.publish()
                        digest.update(block)
                lookup = dict(metadata, expected_size=path.stat().st_size, sha256=digest.hexdigest())
                self.check_control()
                stage = 'Lookup'
                response = client.put(local_file=path, metadata=lookup, empty_file=False, lookup=True)
                if not isinstance(response, dict) or response.get('lookup_supported') is not True:
                    raise TransferFailure('Update the receiver to a version supporting archive synchronization.')
                if response.get('present') is True:
                    # bool is an int subclass, but cannot be a valid remote ID.
                    if type(response.get('id')) is not int or response['id'] <= 0:
                        raise TransferFailure('Receiver did not return a valid transfer acknowledgement.')
                    return response['id']
                if response.get('present') is not False:
                    raise TransferFailure('Receiver returned an invalid source lookup.')
                self.check_control()
            stage = 'Camera metadata upload' if metadata['type'] == constants.CAMERA else 'Upload'
            upload_options = {}
            if metadata['type'] != constants.CAMERA:
                self.progress['upload'] = dict(name=path.name, bytes=0, total=path.stat().st_size)
                upload_options = dict(upload_limit=self.upload_limit, progress_callback=self.upload_progress,
                                      upload_wait=self.stop_event.wait)
            result = client.put(local_file=path, metadata=metadata, empty_file=False, **upload_options)
            if not isinstance(result, dict) or type(result.get('id')) is not int or result['id'] <= 0:
                raise TransferFailure('Receiver did not return a valid transfer acknowledgement.')
            if metadata['type'] != constants.CAMERA:
                self.progress['files'] += 1
                self.progress['bytes'] += metadata.get('file_size', 0)
            return result['id']
        except ConnectionFailure as exc:
            target = entry.name if metadata['type'] == constants.CAMERA else path.name
            cause = exc.__cause__ or exc
            detail = ' '.join(str(exc).split())
            raise ConnectionFailure('{0} failed for "{1}": {2}: {3}'.format(stage, target, type(cause).__name__, detail)) from exc
        finally:
            self.progress.pop('upload', None)
            client.close()

    def transfer_unit(self, entry, media_type):
        thumbnail = None
        if entry.thumbnail_uuid:
            thumbnail = models.IndiAllSkyDbThumbnailTable.query.filter_by(uuid=entry.thumbnail_uuid).first()
            if thumbnail is None or not thumbnail.getFilesystemPath().is_file() or thumbnail.getFilesystemPath().stat().st_size == 0:
                return False
        send_parent = entry.sync_id is None
        if send_parent and (not entry.getFilesystemPath().is_file() or entry.getFilesystemPath().stat().st_size == 0):
            return False
        metadata = metadata_for(entry, media_type)
        # Keep IDs in local variables until BOTH requests succeed. check_control()
        # commits between requests, so assigning entry.sync_id earlier would
        # checkpoint a partial unit. Retrying a parent may delete its thumbnail.
        parent_id = self.transfer(entry, metadata) if send_parent else entry.sync_id
        thumbnail_id = None
        if thumbnail and (send_parent or thumbnail.sync_id is None):
            thumbnail_id = self.transfer(thumbnail, metadata_for(thumbnail, constants.THUMBNAIL, metadata))
        entry.sync_id = parent_id
        if thumbnail_id is not None:
            thumbnail.sync_id = thumbnail_id
        db.session.commit()
        return True

    def execute(self):
        from .config import IndiAllSkyConfig
        from .filetransfer.exceptions import ConnectionFailure, CertificateValidationFailure, AuthenticationFailure, TransferFailure

        task = db.session.get(models.IndiAllSkyDbTaskQueueTable, self.task_id)
        if not task or task.state not in ACTIVE_STATES:
            return
        self.schedule_revision = task.data.get('schedule_revision')
        self.progress = dict(task_id=self.task_id, state='running', scheduled=self.schedule_revision is not None,
                             started=datetime.now().isoformat(),
                             completed=0, total=0, skipped=0, files=0, bytes=0, message='Preparing synchronization.')
        outcome = 'complete'
        reason = None
        try:
            # Queued tasks from before speed limits were introduced stay valid.
            self.upload_limit = validate_upload_limit(task.data.get('upload_limit', 0))
            self.config = IndiAllSkyConfig().config
            self.destination = validate_destination(self.config)
            if task.data.get('destination') != self.destination:
                raise ValueError('The destination changed after this run was requested.')
            self.check_control()
            types = task.data['types']
            # Settle recently written files and exclude later inserts, even if
            # their dates are older. Capture must not extend this run forever.
            cutoff = datetime.now() - timedelta(minutes=10)
            bounds = {name: db.session.query(func.max(MEDIA[name][0].id)).scalar() or 0 for name in types}
            self.progress['cutoff'] = cutoff.isoformat()
            self.progress['types'] = types
            self.progress['bounds'] = bounds
            self.progress['total'] = sum(self.candidate_query(MEDIA[name][0], bounds[name], cutoff).count() for name in types)
            self.progress['message'] = 'Synchronization running.'
            task.setRunning()
            self.publish(force=True)
            logger.info('Archive SyncAPI run %d started: %d pending items', self.task_id, self.progress['total'])
            cameras = models.IndiAllSkyDbCameraTable.query.filter_by(local=True, hidden=False).all()
            for camera in cameras:
                camera.sync_id = self.transfer(camera, metadata_for(camera, constants.CAMERA))
                db.session.commit()
            last_log = time.monotonic()
            # Merge sorted pages, not the entire archive in memory. Type and ID
            # break equal-date ties; thumbnails stay inside transfer_unit().
            candidates = heapq.merge(*(self.candidate_entries(name, bounds[name], cutoff) for name in types))
            for _, name, entry_id in candidates:
                self.check_control()
                model, media_type, label = MEDIA[name]
                entry = db.session.get(model, entry_id, populate_existing=True)
                self.progress['current'] = label
                try:
                    complete = entry is not None and self.transfer_unit(entry, media_type)
                except FileNotFoundError:
                    db.session.rollback()
                    complete = False
                self.progress['completed' if complete else 'skipped'] += 1
                self.publish()
                if time.monotonic() - last_log >= 30:
                    logger.info('Archive SyncAPI run %d: %d completed, %d skipped', self.task_id, self.progress['completed'], self.progress['skipped'])
                    last_log = time.monotonic()
            message = 'Synchronization finished.' if not self.progress['skipped'] else 'Finished with missing local files; skipped items remain unsynchronized.'
        except SyncStopped as exc:
            outcome, message = 'cancelled', str(exc)
        except CertificateValidationFailure:
            outcome, message = 'failed', 'Receiver certificate validation failed. Check the SyncAPI certificate settings.'
            reason = 'certificate'
        except AuthenticationFailure:
            outcome, message = 'failed', 'Receiver authentication failed. Check the SyncAPI account and API key.'
            reason = 'authentication'
        except ConnectionFailure as exc:
            continuation = 'The schedule will check the receiver again.' if self.schedule_revision is not None else 'Press Sync now to continue.'
            outcome, message = 'failed', '{0} {1}'.format(exc, continuation)
            reason = 'connection'
        except (TransferFailure, ValueError) as exc:
            outcome, message = 'failed', str(exc)
            reason = 'configuration_or_receiver'
        except Exception:
            outcome, message = 'failed', 'Synchronization stopped due to a local or receiver error. Details are available at debug log level.'
            logger.debug('Archive SyncAPI exception', exc_info=True)
            reason = 'unexpected'
        # This run is terminal. A manual request or an enabled schedule may
        # create a separate run for the remaining items.
        db.session.rollback()
        self.progress.update(state=outcome, reason=reason, message=message, finished=datetime.now().isoformat())
        task = db.session.get(models.IndiAllSkyDbTaskQueueTable, self.task_id)
        if task:
            if outcome == 'complete':
                task.setSuccess(message)
            elif outcome == 'cancelled':
                task.setExpired()
            else:
                task.setFailed(message[:255])
        self.publish(force=True)
        log = logger.warning if outcome == 'failed' else logger.info
        log('Archive SyncAPI run %d: %s (%d completed, %d skipped)', self.task_id, message,
            self.progress['completed'], self.progress['skipped'])
