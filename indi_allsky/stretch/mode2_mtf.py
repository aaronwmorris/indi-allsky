### Mode 2 stretch is the Midtone Transfer Function based on PixInsight and Siril
###
### https://pixinsight.com/doc/tools/HistogramTransformation/HistogramTransformation.html
### https://siril.readthedocs.io/en/latest/processing/stretching.html

import time
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSky_Mode2_MTF_Stretch(object):

    def __init__(self, config, bin_v, night_v, moonmode_v, mask=None):
        self.config = config

        self.bin_v = bin_v
        self.night_v = night_v
        self.moonmode_v = moonmode_v


    def main(self, data, image_bit_depth):
        if self.night_v.value:
            # night
            if self.moonmode_v.value and not self.config.get('IMAGE_STRETCH', {}).get('MOONMODE'):
                logger.info('Moon mode stretching disabled')
                return data, False
        else:
            # daytime
            if not self.config.get('IMAGE_STRETCH', {}).get('DAYTIME'):
                return data, False


        stretched_image = self.stretch(data, image_bit_depth)


        return stretched_image, True


    def stretch(self, data, image_bit_depth):

        shadows = 0
        midtones = 0.25
        highlights = 1

        mtf_start = time.time()


        if image_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16

        data_max = 2 ** image_bit_depth


        if isinstance(self._mtf_lut, type(None)):
            # only need to generate the lookup table once
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)


            lut = (range_array - shadows) / (highlights - shadows)

            lut = ((midtones - 1) * lut) / (((2 * midtones - 1) * lut) - midtones)


            lut[lut < 0] = 0  # clip low end
            lut[lut > data_max] = data_max  # clip high end

            lut = lut.astype(numpy_dtype)  # this must come after clipping

            self._mtf_lut = lut


        # apply lookup table
        stretched_image = self._mtf_lut.take(data, mode='raise')


        levels_elapsed_s = time.time() - mtf_start
        logger.info('Image levels in %0.4f s', levels_elapsed_s)

        return stretched_image



