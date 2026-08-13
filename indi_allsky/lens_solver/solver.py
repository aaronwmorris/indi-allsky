import logging
import math
import time

import cv2
import numpy
from scipy.spatial import cKDTree

from . import catalog as catalog_mod
from . import fitting
from .detection import StarDetector
from .fitting import FitEngine
from .fitting import SolveContext

logger = logging.getLogger('indi_allsky')


MIN_DETECTED_STARS = 30
# memory budget for detection label maps on 512MB hosts, not a timing knob
MAX_SOLVE_PIXELS = 16_000_000


def _chooseDownscaleFactor(native_width, native_height, initial_diameter):
    """Integer downscale factor for detection, chosen so it never pushes
    the working diameter below MIN_VIABLE_DIAMETER_PX -- an oversized
    image downscales less aggressively (slower solve), never refuses.
    """
    total_pixels = native_width * native_height
    scale = 1
    if total_pixels > MAX_SOLVE_PIXELS:
        scale = int(math.ceil(math.sqrt(total_pixels / float(MAX_SOLVE_PIXELS))))
    while scale > 1 and (initial_diameter / scale) < fitting.MIN_VIABLE_DIAMETER_PX:
        scale -= 1
    return max(1, scale)


class IndiAllSkyLensSolver(object):
    def __init__(self, config):
        self.config = config
        self._detector = StarDetector(config)

        self._residual_evals = 0
        self._predict_calls = 0
        self._coarse_s = 0.0
        self._fit_s = 0.0

    @property
    def last_n_labels(self):
        return self._detector.last_n_labels

    @property
    def last_component_flood(self):
        return self._detector.last_component_flood

    def loadCatalog(self, mag_limit=catalog_mod.CATALOG_MAG_LIMIT):
        return catalog_mod.loadCatalog(mag_limit)

    def buildExclusionMask(self, image_shape):
        return self._detector.buildExclusionMask(image_shape)

    def detectStars(self, image_gray):
        return self._detector.detectStars(image_gray)

    def fitParameters(self, detections, catalog, latitude, longitude, obstime_unix,
                       initial_params, image_width, image_height):
        self._residual_evals = 0
        self._predict_calls = 0
        self._coarse_s = 0.0
        self._fit_s = 0.0

        # public entry point takes arbitrary catalogs -- enforce the
        # validated density here, not just in loadCatalog()'s default
        if (catalog.shape[0] > catalog_mod.CATALOG_VALIDATED_ROW_CEILING
                or (catalog.shape[0] > 0
                    and float(numpy.max(catalog[:, 2])) > catalog_mod.CATALOG_MAG_LIMIT + catalog_mod.CATALOG_VALIDATION_EPSILON_MAG)):
            return {
                'success': False,
                'reason': 'catalog_not_validated',
                'message': 'Catalog is denser than the validated regime '
                           '(mag_limit <= {0:.1f}); a denser catalog is '
                           'unsupported and can silently degrade solve '
                           'accuracy.'.format(catalog_mod.CATALOG_MAG_LIMIT),
                'stars_matched': 0,
            }

        p0 = numpy.array(initial_params, dtype=numpy.float64)
        diameter0 = p0[3]

        center_x = image_width / 2.0 + p0[4]
        center_y = image_height / 2.0 - p0[5]
        detections = fitting._truncateDetections(
            detections, center_x, center_y, fitting.MAX_DETECTED_STARS)

        engine = FitEngine(SolveContext(
            detections=detections,
            tree=cKDTree(detections[:, :2]) if len(detections) > 0 else None,
            catalog=catalog,
            latitude=latitude,
            longitude=longitude,
            obstime_unix=obstime_unix,
            image_width=image_width,
            image_height=image_height,
            min_alt_rad=numpy.radians(fitting.MIN_STAR_ALT_DEG),
            initial_params=p0,
        ))
        try:
            return engine.fitWithFallbacks(p0, diameter0)
        finally:
            self._residual_evals = engine.residual_evals
            self._predict_calls = engine.predict_calls
            self._coarse_s = engine.coarse_s
            self._fit_s = engine.fit_s

    def solve(self, image_file, latitude, longitude, obstime_unix, initial_values):
        """Detect stars and fit the 6 geometric overlay parameters.
        initial_values/values use the VirtualSky form-field keys; every
        return is a full success or a structured failure, always with a
        timing dict.
        """
        t_start = time.monotonic()
        timing = {
            'decode_s': 0.0, 'detect_s': 0.0, 'catalog_s': 0.0, 'coarse_s': 0.0,
            'fit_s': 0.0, 'total_s': 0.0, 'residual_evals': 0, 'predict_calls': 0,
            'megapixels': 0.0, 'n_labels': 0,
        }

        def finish(result):
            # every return path gets the timing dict and the log line
            result['timing'] = dict(timing)
            result['timing']['total_s'] = round(time.monotonic() - t_start, 3)
            q = result.get('quality', {})
            logger.info(
                'Lens solver: %.2f MP, %d labels, %d detected, %d matched, '
                'rms %s px (decode %.3fs detect %.3fs catalog %.3fs coarse '
                '%.3fs fit %.3fs total %.3fs)',
                timing['megapixels'], timing['n_labels'],
                q.get('stars_detected', 0), q.get('stars_matched', 0),
                ('%.2f' % q['rms_px']) if 'rms_px' in q else 'n/a',
                timing['decode_s'], timing['detect_s'], timing['catalog_s'],
                timing['coarse_s'], timing['fit_s'], result['timing']['total_s'])
            return result

        t0 = time.monotonic()
        img = cv2.imread(str(image_file), cv2.IMREAD_GRAYSCALE)
        timing['decode_s'] = round(time.monotonic() - t0, 3)

        if img is None:
            return finish({
                'success': False,
                'reason': 'image_unreadable',
                'message': 'Unable to read image file',
                'quality': {'stars_detected': 0, 'stars_matched': 0},
            })

        native_height, native_width = img.shape
        timing['megapixels'] = round((native_width * native_height) / 1.0e6, 3)

        initial_diameter = float(initial_values['IMAGE_CIRCLE_DIAMETER'])

        # refusal keys on the NATIVE diameter; the downscale guard never
        # pushes a viable native circle under the floor
        if initial_diameter < fitting.MIN_VIABLE_DIAMETER_PX:
            return finish({
                'success': False,
                'reason': 'image_circle_too_small',
                'message': ('Image circle diameter ({0:d} px) is smaller than '
                            'the minimum the solver can reliably calibrate '
                            '({1:d} px).').format(
                                int(round(initial_diameter)), fitting.MIN_VIABLE_DIAMETER_PX),
                'quality': {'stars_detected': 0, 'stars_matched': 0},
            })

        scale = _chooseDownscaleFactor(native_width, native_height, initial_diameter)

        if scale > 1:
            work_width = max(1, native_width // scale)
            work_height = max(1, native_height // scale)
            work_img = cv2.resize(img, (work_width, work_height), interpolation=cv2.INTER_AREA)
        else:
            work_width, work_height = native_width, native_height
            work_img = img

        t0 = time.monotonic()
        detections = self.detectStars(work_img)
        timing['detect_s'] = round(time.monotonic() - t0, 3)
        timing['n_labels'] = int(self.last_n_labels)
        stars_detected = int(detections.shape[0])

        if self.last_component_flood:
            return finish({
                'success': False,
                'reason': 'too_many_components',
                'message': ('Too many bright regions detected in this frame '
                            'to process reliably. Check DETECT_MASK or '
                            'ORB_PROPERTIES if this persists.'),
                'quality': {'stars_detected': 0, 'stars_matched': 0},
            })

        if stars_detected < MIN_DETECTED_STARS:
            return finish({
                'success': False,
                'reason': 'too_few_stars',
                'message': 'Only {0:d} stars detected -- sky may be cloudy '
                           'or too bright.'.format(stars_detected),
                'quality': {'stars_detected': stars_detected, 'stars_matched': 0},
            })

        initial_params = numpy.array([
            float(initial_values['AZIMUTH_ANGLE']),
            float(initial_values['LATITUDE_OFFSET']),
            float(initial_values['LONGITUDE_OFFSET']),
            initial_diameter / scale,
            float(initial_values['OFFSET_X']) / scale,
            float(initial_values['OFFSET_Y']) / scale,
        ])

        t0 = time.monotonic()
        catalog = self.loadCatalog()
        timing['catalog_s'] = round(time.monotonic() - t0, 3)

        fit = self.fitParameters(
            detections, catalog, latitude, longitude, obstime_unix,
            initial_params, work_width, work_height)

        timing['coarse_s'] = round(self._coarse_s, 3)
        timing['fit_s'] = round(self._fit_s, 3)
        timing['residual_evals'] = int(self._residual_evals)
        timing['predict_calls'] = int(self._predict_calls)

        quality = {
            'stars_detected': stars_detected,
            'stars_matched': int(fit['stars_matched']),
        }
        if 'final_match_radius' in fit:
            # scale pixel-valued fields back to native resolution
            quality['final_match_radius'] = round(float(fit['final_match_radius']) * scale, 2)
        if 'rms_px' in fit:
            quality['rms_px'] = round(float(fit['rms_px']) * scale, 2)

        if not fit['success']:
            return finish({
                'success': False,
                'reason': fit['reason'],
                'message': fit['message'],
                'quality': quality,
            })

        p = fit['params']
        diameter_native = p[3] * scale
        offset_x_native = p[4] * scale
        offset_y_native = p[5] * scale

        values = {
            'AZIMUTH_ANGLE': round(float(p[0]), 1),
            'LATITUDE_OFFSET': round(float(p[1]), 2),
            'LONGITUDE_OFFSET': round(float(p[2]), 2),
            'IMAGE_CIRCLE_DIAMETER': int(round(diameter_native)),
            'OFFSET_X': int(round(offset_x_native)),
            'OFFSET_Y': int(round(offset_y_native)),
        }

        # renderer-agnostic geometry for future non-VirtualSky consumers
        geometry = {
            'zenith_x': round(native_width / 2.0 + offset_x_native, 1),
            'zenith_y': round(native_height / 2.0 - offset_y_native, 1),
            'rotation_deg': round(float(p[0]), 2),
            'horizon_diameter_px': int(round(diameter_native)),
            'tilt_ns_deg': round(float(p[1]), 2),
            'tilt_ew_deg': round(float(p[2]), 2),
        }

        message = 'Matched {0:d} stars, RMS {1:0.1f} px'.format(
            quality['stars_matched'], quality['rms_px'])
        if fit['partial']:
            message += ' (tilt could not be determined -- left unchanged)'

        return finish({
            'success': True,
            'values': values,
            'geometry': geometry,
            'quality': quality,
            'partial': bool(fit['partial']),
            'message': message,
        })
