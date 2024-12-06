### Mode 2 stretch is the Midtone Transfer Function based on PixInsight and Siril
###
### https://pixinsight.com/doc/tools/HistogramTransformation/HistogramTransformation.html
### https://siril.readthedocs.io/en/latest/processing/stretching.html

import time
import numpy
import logging

from .stretchBase import IndiAllSky_Stretch_Base

logger = logging.getLogger('indi_allsky')


class IndiAllSky_Mode2_MTF_Stretch(IndiAllSky_Stretch_Base):

    operation_count = 1


    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Mode2_MTF_Stretch, self).__init__(*args, **kwargs)

        self.shadows = self.config.get('IMAGE_STRETCH', {}).get('MODE2_SHADOWS', 0.0)
        self.midtones = self.config.get('IMAGE_STRETCH', {}).get('MODE2_MIDTONES', 0.35)
        self.highlights = self.config.get('IMAGE_STRETCH', {}).get('MODE2_HIGHLIGHTS', 1.0)

        self._mtf_lut = None


    def stretch(self, data, image_bit_depth):
        #logger.info('MTF: Shadows - Shadows %0.2f, Midtones %0.2f, Highlights %0.2f', self.shadows, self.midtones, self.highlights)

        mtf_start = time.time()


        if isinstance(self._mtf_lut, type(None)):
            # only need to generate the lookup table once
            if image_bit_depth == 8:
                numpy_dtype = numpy.uint8
            else:
                numpy_dtype = numpy.uint16


            data_max = (2 ** image_bit_depth) - 1


            range_array = numpy.arange(0, data_max + 1, dtype=numpy.float32)
            shadows_val = int(self.shadows * data_max)
            highlights_val = int(self.highlights * data_max)

            # these will result in 1.0 normalized values
            lut = (range_array - shadows_val) / (highlights_val - shadows_val)
            lut = ((self.midtones - 1) * lut) / (((2 * self.midtones - 1) * lut) - self.midtones)

            # back to real values
            lut = lut * data_max


            lut[lut < 0] = 0  # clip low end
            lut[lut > data_max] = data_max  # clip high end

            lut = lut.astype(numpy_dtype)  # this must come after clipping

            #logger.info('Min: %d, Max: %d', numpy.min(lut), numpy.max(lut))

            self._mtf_lut = lut


        stretched_image = data
        for x in range(self.operation_count):
            stretched_image = self._mtf_lut.take(stretched_image, mode='raise')


        levels_elapsed_s = time.time() - mtf_start
        logger.info('Stretch in %0.4f s', levels_elapsed_s)

        return stretched_image



class IndiAllSky_Mode2_MTF_Stretch_x2(IndiAllSky_Mode2_MTF_Stretch):

    operation_count = 2

