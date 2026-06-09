import time
from pathlib import Path
import cv2
import numpy
import sep
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyStarsSEP(object):
    """Star detection using SEP (Source Extractor Python).

    Provides the same interface as IndiAllSkyStars so it can be used as a
    drop-in replacement in the processing pipeline.  SEP estimates and
    subtracts the sky background before extracting sources, which makes it
    significantly more robust on real sky images than template matching.
    """

    def __init__(self, config, mask=None):
        self.config = config

        self._sqm_mask_dict = mask

        self._star_mask_dict = dict()
        for binning in self._sqm_mask_dict.keys():
            self._star_mask_dict[binning] = None

        self._detectionThreshold = self.config.get('DETECT_STARS_SEP_THOLD', 5.0)

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def detectObjects(self, original_data, binning):
        if isinstance(self._star_mask_dict[binning], type(None)):
            self._generateStarMask(original_data, binning)

        # build SEP mask: nonzero = excluded (inverse of indi-allsky convention)
        indi_mask = self._star_mask_dict[binning]
        if indi_mask is not None:
            sep_mask = (indi_mask == 0).astype(numpy.uint8)
        else:
            sep_mask = None

        if len(original_data.shape) == 2:
            grey = original_data
        else:
            grey = cv2.cvtColor(original_data, cv2.COLOR_BGR2GRAY)

        data = numpy.ascontiguousarray(grey.astype(numpy.float32))

        sep_start = time.time()

        bkg = sep.Background(data, mask=sep_mask)
        data_sub = data - bkg

        try:
            objects = sep.extract(data_sub, self._detectionThreshold, err=bkg.globalrms, mask=sep_mask)
        except Exception as e:
            logger.error('SEP extraction error: %s', e)
            objects = []

        sep_elapsed_s = time.time() - sep_start
        logger.info('Detected %d stars in %0.4f s', len(objects), sep_elapsed_s)

        blobs = [(float(obj['x']), float(obj['y'])) for obj in objects]

        self._drawCircles(original_data, objects)

        return blobs


    def _generateStarMask(self, img, binning):
        logger.info('Generating mask based on SQM_ROI')

        if not isinstance(self._sqm_mask_dict[binning], type(None)):
            self._star_mask_dict[binning] = self._sqm_mask_dict[binning]
            return

        image_height, image_width = img.shape[:2]

        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1 = int(sqm_roi[0] / binning)
            y1 = int(sqm_roi[1] / binning)
            x2 = int(sqm_roi[2] / binning)
            y2 = int(sqm_roi[3] / binning)
        except IndexError:
            logger.warning('Using central ROI for star detection')
            sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
            x1 = int((image_width / 2) - (image_width / sqm_fov_div))
            y1 = int((image_height / 2) - (image_height / sqm_fov_div))
            x2 = int((image_width / 2) + (image_width / sqm_fov_div))
            y2 = int((image_height / 2) + (image_height / sqm_fov_div))

        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, cv2.FILLED)

        self._star_mask_dict[binning] = mask


    def _drawCircles(self, img, objects):
        if not self.config.get('DETECT_DRAW'):
            return

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()

        logger.info('Draw circles around objects')
        for obj in objects:
            cx = int(obj['x'])
            cy = int(obj['y'])
            r = max(4, int(obj['a'] * 3))
            cv2.circle(img, (cx, cy), r, tuple(color_bgr), thickness=1)
