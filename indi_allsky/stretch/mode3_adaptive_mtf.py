### Mode 3 stretch is the Midtone Transfer Function based on PixInsight and Siril
###
### https://pixinsight.com/forum/index.php?threads/auto-histogram-settings-to-replicate-auto-stf.8205/#post-55143
### https://siril.readthedocs.io/en/latest/processing/stretching.html

import time
import numpy
import logging

from .stretchBase import IndiAllSky_Stretch_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Mode3_Adaptive_MTF_Stretch(IndiAllSky_Stretch_Base):

    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Mode3_Adaptive_MTF_Stretch, self).__init__(*args, **kwargs)

        self.black_clip = self.config.get('IMAGE_STRETCH', {}).get('MODE3_BLACK_CLIP', -2.8)
        self.shadows = self.config.get('IMAGE_STRETCH', {}).get('MODE3_SHADOWS', 0.0)
        self.midtones = self.config.get('IMAGE_STRETCH', {}).get('MODE3_MIDTONES', 0.35)
        self.highlights = self.config.get('IMAGE_STRETCH', {}).get('MODE3_HIGHLIGHTS', 1.0)
        
        self.stride = 20
        self.scale_factor = 1.4826


    def stretch(self, data, image_bit_depth):
        #logger.info('MTF: Shadows - Shadows %0.2f, Midtones %0.2f, Highlights %0.2f', self.shadows, self.midtones, self.highlights)

        stretch_start = time.time()

        if image_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16

        data_max = (2 ** image_bit_depth) - 1
        shadows_val = int(self.shadows * data_max)
        highlights_val = int(self.highlights * data_max)

        if data.shape[0] > self.stride and data.shape[1] > self.stride:
            samples = data[::self.stride, ::self.stride]
        else:
            samples = data
        
        # these will result in 0.0 to 1.0 normalized values
        samples = (samples / data_max).astype(numpy.float32)
        axis = (0, 1)

        m = numpy.mean(numpy.median(samples, axis=axis)).astype(numpy.float32)
        d = numpy.mean(self._mdev(samples, axis)).astype(numpy.float32)
        c = numpy.clip(m + self.black_clip * self.scale_factor * d, 0.0, 1.0)

        lut = numpy.arange(data_max + 1, dtype=numpy.float32) / data_max
        
        stretched_lut = self._mtf(self._mtf(self.midtones, m - c), numpy.maximum(0.0, (lut - c) / (1 - c)))
        stretched_lut = stretched_lut * data_max  # scale back to real values
        stretched_lut = self._normalize_to_range(stretched_lut, 0 - shadows_val, data_max + (data_max - highlights_val))
        stretched_lut = numpy.clip(stretched_lut, 0, data_max)
        stretched_lut = stretched_lut.astype(numpy_dtype)
        
        stretched_image = stretched_lut.take(data, mode='raise')

        stretch_elapsed_s = time.time() - stretch_start
        logger.info('Stretch in %0.4f s', stretch_elapsed_s)

        return stretched_image


    def _mdev(self, data, axis=None):
        med = numpy.median(data, axis=axis)
        mad = numpy.abs(data - med)
        return numpy.median(mad) * self.scale_factor


    def _mtf(self, midtones, data):
        a = (midtones - 1) * data
        b = ((2 * midtones - 1) * data) - midtones
        return numpy.divide(a, b, where=b != 0)

    def _normalize_to_range(self, a, min_value, max_value):
        a_min = numpy.min(a)
        a_max = numpy.max(a)

        if a_max - a_min == 0:
            return numpy.full_like(a, (a_min + a_max) / 2)

        return ((a - a_min) / (a_max - a_min)) * (max_value - min_value) + min_value
