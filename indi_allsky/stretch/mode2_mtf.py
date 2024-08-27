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

    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Mode2_MTF_Stretch, self).__init__(*args, **kwargs)

        self.shadows = self.config.get('IMAGE_STRETCH', {}).get('MODE2_SHADOWS', 0.0)
        self.midtones = self.config.get('IMAGE_STRETCH', {}).get('MODE2_MIDTONES', 0.25)
        self.highlights = self.config.get('IMAGE_STRETCH', {}).get('MODE2_HIGHLIGHTS', 1.0)

        self._mtf_lut = None


    def main(self, data, image_bit_depth):

        stretched_image = self.stretch(data, image_bit_depth)


        return stretched_image, True


    def stretch(self, data, image_bit_depth):

        mtf_start = time.time()


        if image_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16

        data_max = (2 ** image_bit_depth) - 1


        if isinstance(self._mtf_lut, type(None)):
            # only need to generate the lookup table once
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)


            lut = (range_array - self.shadows) / (self.highlights - self.shadows)

            lut = ((self.midtones - 1) * lut) / (((2 * self.midtones - 1) * lut) - self.midtones)


            lut[lut < 0] = 0  # clip low end
            lut[lut > data_max] = data_max  # clip high end

            lut = lut.astype(numpy_dtype)  # this must come after clipping

            self._mtf_lut = lut


        stretched_image = self._mtf_lut.take(data, mode='raise')


        levels_elapsed_s = time.time() - mtf_start
        logger.info('Stretch in %0.4f s', levels_elapsed_s)

        return stretched_image



