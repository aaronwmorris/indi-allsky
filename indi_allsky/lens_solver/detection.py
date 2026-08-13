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
                # (mirrors BaseView._load_detection_mask, binning 1)
                mask_processor = MaskProcessor(self.config)
                mask_processor.image = user_mask
                if self.config.get('IMAGE_ROTATE'):
                    mask_processor.rotate_90()
                if self.config.get('IMAGE_ROTATE_ANGLE'):
                    mask_processor.rotate_angle()
                if self.config.get('IMAGE_FLIP_V'):
                    mask_processor.flip_v()
                if self.config.get('IMAGE_FLIP_H'):
                    mask_processor.flip_h()
                if self.config.get('IMAGE_CROP_IMAGE_CIRCLE') or self.config.get('IMAGE_CROP_ROI'):
                    mask_processor.crop_image()
                if self.config.get('IMAGE_SCALE') and self.config['IMAGE_SCALE'] != 100:
                    mask_processor.scale_image()
                user_mask = mask_processor.image

                if user_mask.shape != (height, width):
                    user_mask = cv2.resize(user_mask, (width, height))

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

        _mean, stddev = cv2.meanStdDev(signal)   # 4x faster than numpy.std
        std = float(stddev[0, 0])
        threshold_value = max(MIN_DETECTION_THRESHOLD, DETECTION_SIGMA * std)
        _, thresh = cv2.threshold(signal, threshold_value, 255, cv2.THRESH_BINARY)

        mask = self.buildExclusionMask(image_gray.shape)
        if mask is not None:
            thresh = cv2.bitwise_and(thresh, mask)

        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            thresh, connectivity=8)
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
