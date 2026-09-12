import logging

import cv2
import numpy

from ..maskProcessing import MaskProcessor

logger = logging.getLogger('indi_allsky')


# estimate the background on a decimated copy (~40x faster than full-res
# medianBlur, identical estimate -- background is smooth vs a star PSF)
BACKGROUND_DECIMATION_FACTOR = 8
DECIMATED_MEDIAN_BLUR_KERNEL = 5
# detection threshold = max(MIN_DETECTION_THRESHOLD, DETECTION_SIGMA * std)
DETECTION_SIGMA = 4.0
MIN_DETECTION_THRESHOLD = 8.0
# hot pixels are ~1px at any resolution; deliberately no upper area cap --
# one was tried and silently discarded real bloomed/defocused stars
MIN_COMPONENT_AREA = 2
# flood of components (daylight, noise storm) returns a structured failure
MAX_COMPONENTS = 5000
# binarize AFTER mask resize -- bilinear resize produces gray edge pixels
MASK_BINARIZE_THRESHOLD = 127
# sun/moon orb border band: radius * MULTIPLIER + MARGIN_PX
ORB_BAND_RADIUS_MULTIPLIER = 2
ORB_BAND_MARGIN_PX = 4
ORB_RADIUS_DEFAULT = 9


class StarDetector(object):
    def __init__(self, config):
        self.config = config

        # populated by detectStars() for the solver's reason codes and timing
        self.last_n_labels = 0
        self.last_component_flood = False
        self.use_sky_hints = False
        self.sensor_shape = None
        self.binning = 1

    def preferredDetections(self, detections, image_shape):
        """SQM_ROI is a sensor-coordinate hint, never an exclusion of other sky."""
        roi = self.config.get('SQM_ROI')
        if not self.sensor_shape or not isinstance(roi, (list, tuple)) or len(roi) != 4:
            return detections[:0]
        try:
            if any(isinstance(v, bool) or not numpy.isfinite(v) for v in roi):
                return detections[:0]
            x1, y1, x2, y2 = [int(v / self.binning) for v in roi]
            height, width = self.sensor_shape
            if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
                return detections[:0]
            mask = numpy.zeros(self.sensor_shape, dtype=numpy.uint8)
            mask[y1:y2, x1:x2] = 255
            mask = self._transformMask(mask, image_shape, self.binning)
            xy = detections[:, :2].astype(int)
            return detections[mask[xy[:, 1], xy[:, 0]] > MASK_BINARIZE_THRESHOLD]
        except (TypeError, ValueError, OverflowError):
            return detections[:0]

    def _transformMask(self, mask, image_shape, binning=1):
        processor = MaskProcessor(self.config)
        processor.image = mask
        processor.binning = binning
        processor.rotate_90()
        processor.rotate_angle()
        processor.flip_v()
        processor.flip_h()
        if self.config.get('IMAGE_CROP_IMAGE_CIRCLE') or self.config.get('IMAGE_CROP_ROI'):
            processor.crop_image()
        # Focus frames skip scale and borders in the image pipeline too.
        if not (self.use_sky_hints and self.config.get('FOCUS_MODE')):
            if self.config.get('IMAGE_SCALE') and self.config['IMAGE_SCALE'] != 100:
                processor.scale_image()
            if self.use_sky_hints:
                processor.add_border()
        height, width = image_shape[:2]
        if processor.image.shape != (height, width):
            return cv2.resize(processor.image, (width, height))
        return processor.image

    def buildExclusionMask(self, image_shape):
        # 255 = usable sky, 0 = excluded; None when nothing to exclude
        height, width = image_shape[0], image_shape[1]
        mask = numpy.full((height, width), 255, dtype=numpy.uint8)
        have_exclusions = False

        detect_mask_path = self.config.get('DETECT_MASK', '')
        if detect_mask_path:
            user_mask = cv2.imread(str(detect_mask_path), cv2.IMREAD_GRAYSCALE)
            if user_mask is not None:
                # masks are authored in sensor orientation; apply the same
                # transforms the image pipeline applies to captured frames
                binning = 1
                if self.use_sky_hints:
                    binning = self.binning
                    # Older camera records may lack dimensions. Detection masks
                    # are authored at full sensor resolution, before binning.
                    shape = self.sensor_shape or tuple(max(1, n // binning) for n in user_mask.shape)
                    user_mask = cv2.resize(user_mask, shape[::-1])
                user_mask = self._transformMask(user_mask, image_shape, binning)

                # binarize AFTER resize
                binary_mask = numpy.zeros_like(user_mask)
                binary_mask[user_mask > MASK_BINARIZE_THRESHOLD] = 255

                mask = cv2.bitwise_and(mask, binary_mask)
                have_exclusions = True
            else:
                logger.warning('Lens solver: unable to read DETECT_MASK %s', detect_mask_path)

        # sun/moon orbs ride the border and look like bright stars; mask
        # the band rather than locating the orb
        orb_props = self.config.get('ORB_PROPERTIES', {})
        if orb_props.get('MODE', 'off') != 'off':
            radius = int(orb_props.get('RADIUS', ORB_RADIUS_DEFAULT))
            band = radius * ORB_BAND_RADIUS_MULTIPLIER + ORB_BAND_MARGIN_PX
            mask[:band, :] = 0
            mask[-band:, :] = 0
            mask[:, :band] = 0
            mask[:, -band:] = 0
            have_exclusions = True

        if not have_exclusions:
            return None

        return mask

    def detectStars(self, image_gray):
        # background-subtract, threshold, centroid via connected components
        height, width = image_gray.shape[0], image_gray.shape[1]
        small_width = max(1, width // BACKGROUND_DECIMATION_FACTOR)
        small_height = max(1, height // BACKGROUND_DECIMATION_FACTOR)
        small = cv2.resize(image_gray, (small_width, small_height),
                           interpolation=cv2.INTER_AREA)
        small_background = cv2.medianBlur(small, DECIMATED_MEDIAN_BLUR_KERNEL)
        background = cv2.resize(small_background, (width, height),
                                interpolation=cv2.INTER_LINEAR)
        signal = cv2.subtract(image_gray, background)

        mask = self.buildExclusionMask(image_gray.shape)
        # Excluded lights must not raise the threshold for the permitted sky.
        threshold_masks = (mask, None) if self.use_sky_hints and mask is not None else (None,)
        threshold_value = MIN_DETECTION_THRESHOLD
        for threshold_mask in threshold_masks:
            _mean, stddev = cv2.meanStdDev(signal, mask=threshold_mask)
            threshold_value = max(threshold_value, DETECTION_SIGMA * float(stddev[0, 0]))
            _, thresh = cv2.threshold(signal, threshold_value, 255, cv2.THRESH_BINARY)
            if mask is not None:
                thresh = cv2.bitwise_and(thresh, mask)
            n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
                thresh, connectivity=8)
            if n_labels <= MAX_COMPONENTS:
                break
            # Masked sky can admit too much noise on stretched images. Retry
            # once at the normal threshold, keeping exclusions and the limit.
            del labels, stats, centroids  # release the large label map before retrying
        self.last_n_labels = int(n_labels)

        if n_labels > MAX_COMPONENTS:
            # flooded frame must not surface as "too few stars / cloudy",
            # the opposite of the real cause
            self.last_component_flood = True
            return numpy.zeros((0, 3), dtype=numpy.float64)
        self.last_component_flood = False

        detections = []
        for i in range(1, n_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < MIN_COMPONENT_AREA:
                continue      # hot pixels

            # flux from the component's bounding box ROI, never a
            # full-image scan (that is O(components x pixels))
            x0 = stats[i, cv2.CC_STAT_LEFT]
            y0 = stats[i, cv2.CC_STAT_TOP]
            w0 = stats[i, cv2.CC_STAT_WIDTH]
            h0 = stats[i, cv2.CC_STAT_HEIGHT]
            sub_labels = labels[y0:y0 + h0, x0:x0 + w0]
            sub_signal = signal[y0:y0 + h0, x0:x0 + w0]
            flux = float(sub_signal[sub_labels == i].sum())

            cx, cy = centroids[i]
            detections.append((cx, cy, flux))

        if not detections:
            return numpy.zeros((0, 3), dtype=numpy.float64)

        det = numpy.array(detections, dtype=numpy.float64)
        return det[numpy.argsort(det[:, 2])[::-1]]
