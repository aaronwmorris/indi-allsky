### Mode 2 stretch is the Midtone Transfer Function based on PixInsight and Siril
###
### https://pixinsight.com/forum/index.php?threads/auto-histogram-settings-to-replicate-auto-stf.8205/#post-55143
### https://siril.readthedocs.io/en/latest/processing/stretching.html

import time
import numpy
import logging

from .stretchBase import IndiAllSky_Stretch_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Mode2_MTF_Stretch(IndiAllSky_Stretch_Base):

    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Mode2_MTF_Stretch, self).__init__(*args, **kwargs)

        self.black_clip = self.config.get('IMAGE_STRETCH', {}).get('MODE2_BLACK_CLIP', -2.8)
        self.shadows = self.config.get('IMAGE_STRETCH', {}).get('MODE2_SHADOWS', 0.0)
        self.midtones = self.config.get('IMAGE_STRETCH', {}).get('MODE2_MIDTONES', 0.35)
        self.highlights = self.config.get('IMAGE_STRETCH', {}).get('MODE2_HIGHLIGHTS', 1.0)
        
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

        # these will result in 0.0 to 1.0 normalized values
        data = ((data - shadows_val) / (highlights_val - shadows_val)).astype(numpy.float32)

        if len(data.shape) < 3:
            data = numpy.expand_dims(data, axis=2)
        
        data_moveaxis = numpy.moveaxis(data, source=-1, destination=0)

        n = data.shape[2]
        m = (numpy.sum(numpy.median(p) for p in data_moveaxis) / n).astype(numpy.float32)
        d = (numpy.sum(self._mdev(p) for p in data_moveaxis) / n).astype(numpy.float32)
        c = numpy.minimum(numpy.maximum(0.0, m + self.black_clip * self.scale_factor * d), 1.0)
        
        stretched_image = self._mtf(self._mtf(self.midtones, m - c), numpy.maximum(0.0, (data - c) / (1 - c)))
        stretched_image = stretched_image * data_max            # scale back to real values
        stretched_image[stretched_image < 0] = 0                # clip low end
        stretched_image[stretched_image > data_max] = data_max  # clip high end
        stretched_image = stretched_image.astype(numpy_dtype)   # this must come after clipping

        stretch_elapsed_s = time.time() - stretch_start
        logger.info('Stretch in %0.4f s', stretch_elapsed_s)

        return stretched_image


    def _mdev(self, data):
        med = numpy.median(data)
        abs_devs = numpy.abs(data - med)
        return numpy.median(abs_devs) * self.scale_factor


    def _mtf(self, midtones, data):
        a = (midtones - 1) * data
        b = ((2 * midtones - 1) * data) - midtones
        return numpy.divide(a, b, where=b != 0)



class IndiAllSky_Mode2_MTF_Stretch_x2(IndiAllSky_Mode2_MTF_Stretch):
    pass
