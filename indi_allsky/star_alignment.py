"""Session-specific orientation of the published all-sky image.

Only the short-lived solver subprocess imports computer vision and astrometry.
The image worker offers immutable archived exposures and never waits for a solve.
"""
from collections import deque
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

logger = logging.getLogger('indi_allsky')

CONFIRM_INTERVAL = 30       # seconds between independent exposures
RETRY_INTERVAL = 120        # avoid competing with capture in cloudy weather
CHECK_INTERVAL = 600        # also catch a camera moved without a power cycle
MAX_UNVERIFIED = 3600       # do not trust last night's position indefinitely
REFERENCE_INTERVAL = 300    # allow real sky features to move several pixels
SOLVE_TIMEOUT = 180
DIRECTIONS = ('N', 'E', 'S', 'W')


def _status_file(config, camera_uuid):
    key = hashlib.sha256(str(camera_uuid).encode()).hexdigest()
    return Path(config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')) / ('star-alignment-' + key + '.json')


def read_alignment_status(config, camera_uuid):
    try:
        with _status_file(config, camera_uuid).open() as stream:
            record = json.load(stream)
        if record['aligned'] is True and record['updated'] <= time.time() <= record['expires']:
            return 'aligned'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 'pending'


def _agree(first, second):
    """Compare the four physical horizon points in pixels, including circular wrap."""
    if first['image_size'] != second['image_size']:
        return False
    width, height = first['image_size']
    tolerance = 0.02 * min(first['values']['IMAGE_CIRCLE_DIAMETER'], second['values']['IMAGE_CIRCLE_DIAMETER'])
    for key in DIRECTIONS:
        x1, y1 = first['directions'][key]
        x2, y2 = second['directions'][key]
        if math.hypot((x1-x2)*width, (y1-y2)*height) > tolerance:
            return False
    return True


def solve_frame(request):
    import numpy
    from .lens_solver import (IndiAllSkyLensSolver, EFFECTIVE_MIN_MATCHED_STARS,
                              _chooseDownscaleFactor, _rmsGatePx, projectToPixels)

    from .lens_solver.calibration import pipelineSignature

    config = request['config']
    width, height = request['size']
    values = request['seed']
    solver = IndiAllSkyLensSolver(config)
    args = (request['path'], *request['location'], request['timestamp'], values)
    hints = dict(lens_altitude=values['LENS_ALTITUDE'], pointing_azimuth=values['POINTING_AZIMUTH'],
                 sensor_shape=request['sensor_shape'], binning=request['binning'], for_sky_alignment=True)
    result = solver.solve(*args, **hints)
    if not result.get('success'):
        reason = result.get('reason')
        limit = 4_000_000
        diameter = values['IMAGE_CIRCLE_DIAMETER']
        reference = request.get('reference')
        if reference and reason in ('too_many_components', 'lens_model_unconstrained', 'no_match', 'chirality_mismatch'):
            # One bounded retry in a crowded field, with a prior exposure
            # from this setup used only to reject stationary light sources.
            result = solver.solve(*args, **hints, max_work_pixels=limit, stationary_reference=reference)
        elif (reason == 'too_many_components' and
                _chooseDownscaleFactor(width, height, diameter, limit) > _chooseDownscaleFactor(width, height, diameter)):
            result = solver.solve(*args, **hints, max_work_pixels=limit)
    if not result.get('success') or result['partial']:
        logger.info('No verified star alignment: %s', result.get('message', 'partial solution'))
        return None
    values = dict(result['values'])
    # Separable six-parameter fits use the original equisolid lens projection.
    values.setdefault('RADIAL_DISTORTION', 0.0)
    quality = result['quality']
    if ('LENS_ALTITUDE' not in values or 'POINTING_AZIMUTH' not in values
            or values['LATITUDE_OFFSET'] != 0 or values['LONGITUDE_OFFSET'] != 0
            or quality['stars_matched'] < EFFECTIVE_MIN_MATCHED_STARS
            or not 0 <= quality['rms_px'] <= _rmsGatePx(values['IMAGE_CIRCLE_DIAMETER'])):
        return None
    params = [values[key] for key in ('AZIMUTH_ANGLE', 'LATITUDE_OFFSET', 'LONGITUDE_OFFSET',
              'IMAGE_CIRCLE_DIAMETER', 'OFFSET_X', 'OFFSET_Y', 'RADIAL_DISTORTION')]
    x, y = projectToPixels(numpy.zeros(4), numpy.radians([0., 90., 180., 270.]),
                           params, width, height, lens_altitude=values['LENS_ALTITUDE'],
                           pointing_azimuth=values['POINTING_AZIMUTH'])
    if not numpy.isfinite(x).all() or not numpy.isfinite(y).all():
        return None
    return {'image_size': [width, height], 'values': values, 'location': list(request['location']),
            'pipeline': pipelineSignature(config),
            'directions': {key: [float(a/width), float(b/height)] for key, a, b in zip(DIRECTIONS, x, y)}}


class StarAlignment:
    def __init__(self, config):
        self.config = config
        self.camera = None
        self.solution = self.candidate = self.job = None
        self.last_checked = self.next_try = self.last_publish = 0.
        self.frame = None
        self.references = deque(maxlen=9)  # immutable paths only, up to 45 minutes
        self.cancelled = False
        self.last_offer = None
        # Real exposures may take longer than the ordinary status heartbeat.
        cadence = max(float(config.get(k) or 0) for k in ('CCD_EXPOSURE_MAX', 'EXPOSURE_PERIOD', 'EXPOSURE_PERIOD_DAY'))
        self.max_frame_age = max(300., 2*cadence + 60.)
        self.max_gap = max(900., 3*cadence + 90.)

    def _publish(self, force=False):
        mono = time.monotonic()
        if self.camera is None or (not force and mono - self.last_publish < 60):
            return
        self.last_publish = mono
        path = _status_file(self.config, self.camera)
        now = time.time()
        record = {'aligned': self.solution is not None, 'updated': now, 'expires': now + self.max_frame_age}
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.star-alignment-', mode='w', delete=False) as stream:
                tmp = Path(stream.name)
                json.dump(record, stream)
                os.fchmod(stream.fileno(), 0o644)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning('Cannot publish star alignment status: %s', exc)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def _stop_job(self, wait=False):
        if self.job is None:
            return
        process, _, _ = self.job
        self.cancelled = True
        if process.poll() is None:
            process.kill()
        if wait:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                return
        if process.poll() is not None:
            process.stdout.close()
            self.job = None

    def close(self):
        self._stop_job(wait=True)
        self.solution = self.candidate = None
        self._publish(force=True)
        self.camera = self.frame = self.last_offer = None
        self.references.clear()

    def _poll(self, now):
        if not self.job:
            return
        process, stamp, started = self.job
        if process.poll() is None:
            if now - started <= SOLVE_TIMEOUT + 5:
                return
            self._stop_job()
            self.next_try = now + RETRY_INTERVAL
            return

        with process.stdout as stream:
            data = stream.read(16384)
        self.job = None
        if self.cancelled:
            return
        result = None
        if process.returncode == 0:
            try:
                result = json.loads(data)
            except (ValueError, UnicodeError):
                pass
        if result is None:
            self.next_try = now + RETRY_INTERVAL
            return

        if self.solution and _agree(self.solution, result):
            self.last_checked = now
            self.next_try = now + CHECK_INTERVAL
            return  # preserve session identity and stable geometry

        if self.solution:
            # We have positive evidence the camera moved. Suppress old labels
            # immediately, independently confirm before publishing new ones.
            self.solution = None
            self.candidate = None
            self._publish(force=True)

        if self.candidate:
            previous_stamp, previous = self.candidate
            if (CONFIRM_INTERVAL <= stamp - previous_stamp <= self.max_gap
                    and _agree(previous, result)):
                self.solution = dict(result, id=uuid4().hex)
                self.candidate = None
                self.last_checked = now
                self.next_try = now + CHECK_INTERVAL
                self._publish(force=True)
                logger.info('Confirmed star alignment for camera %s', self.camera)
                return
        self.candidate = (stamp, result)
        self.next_try = now + CONFIRM_INTERVAL

    def begin_frame(self, camera_uuid, day_date, night, captured_at, image_size, location):
        try:
            stamp = captured_at.timestamp() if hasattr(captured_at, 'timestamp') else float(captured_at)
            width, height = image_size
            lat, lon = map(float, location[:2])
            if not (math.isfinite(stamp) and stamp >= 0 and width > 0 and height > 0 and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (TypeError, ValueError, OSError, OverflowError):
            if self.frame is not None:
                self.close()
            return None
        size = (width, height)
        site = (lat, lon)
        now = time.monotonic()
        new_session = self.frame is None or self.camera != camera_uuid
        if not new_session:
            prev = self.frame
            # Comparing coordinates to the session origin tolerates GPS jitter.
            new_session = (size != prev['size'] or abs(site[0] - self.origin[0]) > .02
                           or abs((site[1] - self.origin[1] + 180) % 360 - 180) > .02
                           or stamp - prev['timestamp'] > self.max_gap or stamp < prev['timestamp'] - 5
                           or (night and (not prev['night'] or day_date != prev['date'])))
        if new_session:
            self._stop_job()
            self.solution = self.candidate = self.last_offer = None
            self.references.clear()
            if self.camera != camera_uuid and self.camera is not None:
                self._publish(force=True)
            self.camera = camera_uuid
            self.origin = site
            self.next_try = 0.
            self._publish(force=True)
        self.frame = {'timestamp': stamp, 'night': night, 'date': day_date, 'size': size, 'location': site}
        self._poll(now)
        if self.solution and now - self.last_checked > MAX_UNVERIFIED:
            self.solution = self.candidate = None
            self._publish(force=True)
        self._publish()
        return self.solution['directions'] if self.solution else None

    def offer_frame(self, path, *, binning=1, sensor_shape=None):
        now = time.monotonic()
        frame = self.frame
        if not (frame and frame['night'] and path):
            return
        stamp = frame['timestamp']
        if not -5 <= time.time() - stamp <= self.max_frame_age:
            return
        reference = None
        path = str(Path(path).absolute())
        for previous_stamp, previous_path in self.references:
            if REFERENCE_INTERVAL <= stamp-previous_stamp <= MAX_UNVERIFIED and path != previous_path:
                reference = previous_path
                break
        if not self.references or stamp - self.references[-1][0] >= REFERENCE_INTERVAL:
            self.references.append((stamp, path))
        if self.job or now < self.next_try:
            return
        if self.last_offer and (path == self.last_offer[0] or stamp <= self.last_offer[1]):
            return
        if self.candidate and stamp - self.candidate[0] < CONFIRM_INTERVAL:
            return
        lat, lon = frame['location']

        vs = self.config.get('VIRTUALSKY', {})
        width, height = frame['size']
        diameter = float(vs.get('IMAGE_CIRCLE_DIAMETER') or min(width, height))
        if not .5 * min(width, height) <= diameter <= 2 * max(width, height):
            diameter = min(width, height)
        seed = {'AZIMUTH_ANGLE': self.config.get('LENS_AZIMUTH', 0.),
                'LENS_ALTITUDE': self.config.get('LENS_ALTITUDE', 90.),
                'POINTING_AZIMUTH': vs.get('POINTING_AZIMUTH', 0.),
                'LATITUDE_OFFSET': 0., 'LONGITUDE_OFFSET': 0.,
                'IMAGE_CIRCLE_DIAMETER': diameter, 'OFFSET_X': vs.get('OFFSET_X', 0), 'OFFSET_Y': vs.get('OFFSET_Y', 0),
                'RADIAL_DISTORTION': vs.get('RADIAL_DISTORTION', 0.), 'PRECESSION': True}
        if self.candidate or self.solution:
            seed = (self.candidate[1] if self.candidate else self.solution)['values']
        # Only the image-mask configuration is needed by the solver.
        keys = ('DETECT_MASK', 'ORB_PROPERTIES', 'IMAGE_ROTATE', 'IMAGE_ROTATE_ANGLE', 'IMAGE_FLIP_V', 'IMAGE_FLIP_H',
                'IMAGE_CROP_IMAGE_CIRCLE', 'IMAGE_CROP_ROI', 'IMAGE_SCALE', 'LENS_IMAGE_CIRCLE', 'LENS_OFFSET_X',
                'LENS_OFFSET_Y', 'IMAGE_ROTATE_KEEP_SIZE', 'IMAGE_BORDER')
        request = {'config': {k: self.config[k] for k in keys if k in self.config}, 'path': path, 'reference': reference,
                   'seed': seed, 'location': [lat, lon], 'timestamp': stamp, 'size': frame['size'],
                   'binning': binning, 'sensor_shape': sensor_shape}
        try:
            env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
            with tempfile.TemporaryFile() as input_file:
                input_file.write(json.dumps(request, allow_nan=False).encode())
                input_file.seek(0)
                process = subprocess.Popen([sys.executable, '-m', 'indi_allsky.star_alignment'],
                                           cwd=Path(__file__).resolve().parent.parent, env=env,
                                           stdin=input_file, stdout=subprocess.PIPE)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning('Cannot start automatic star alignment: %s', exc)
            self.next_try = now + RETRY_INTERVAL
            return
        self.last_offer = (str(path), stamp)
        self.cancelled = False
        self.job = process, stamp, now


if __name__ == '__main__':
    # Limit work even if the image worker is killed between two exposures.
    signal.alarm(SOLVE_TIMEOUT)
    os.nice(10)
    import cv2
    cv2.setNumThreads(1)
    json.dump(solve_frame(json.load(sys.stdin)), sys.stdout, allow_nan=False)
