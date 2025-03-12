### Mode 1 stretch is based on C code provided by a fellow astronomy enthusiast

import time
import numpy
import logging

from .stretchBase import IndiAllSky_Stretch_Base


logger = logging.getLogger('indi_allsky')


class IndiAllSky_Mode1_Stretch(IndiAllSky_Stretch_Base):

    def __init__(self, *args, **kwargs):
        super(IndiAllSky_Mode1_Stretch, self).__init__(*args, **kwargs)
        self._sqm_mask = kwargs['mask']


        self.gamma = self.config.get('IMAGE_STRETCH', {}).get('MODE1_GAMMA', 3.0)
        self.stddevs = self.config.get('IMAGE_STRETCH', {}).get('MODE1_STDDEVS', 3.0)


        self._numpy_mask = None


    def stretch(self, data, image_bit_depth):
        if isinstance(self._numpy_mask, type(None)):
            # This only needs to be done once
            self._generateNumpyMask(data)


        data = self.mode1_apply_gamma(data, image_bit_depth)

        data = self.mode1_adjustImageLevels(data, image_bit_depth)

        return data


    def mode1_apply_gamma(self, data, image_bit_depth):
        if not self.gamma:
            return data

        logger.info('Applying gamma correction')

        gamma_start = time.time()


        if image_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16


        data_max = (2 ** image_bit_depth) - 1


        range_array = numpy.arange(0, data_max + 1, dtype=numpy.float32)
        lut = (((range_array / data_max) ** (1.0 / self.gamma)) * data_max).astype(numpy_dtype)


        # apply lookup table
        gamma_data = lut.take(data, mode='raise')

        gamma_elapsed_s = time.time() - gamma_start
        logger.info('Image gamma in %0.4f s', gamma_elapsed_s)

        return gamma_data


    def mode1_adjustImageLevels(self, data, image_bit_depth):
        mean, stddev = self._get_image_stddev(data)
        logger.info('Mean: %0.2f, StdDev: %0.2f', mean, stddev)


        levels_start = time.time()


        if image_bit_depth == 8:
            numpy_dtype = numpy.uint8
        else:
            numpy_dtype = numpy.uint16


        data_max = (2 ** image_bit_depth) - 1

        low = int(mean - (self.stddevs * stddev))

        lowPercent  = (low / data_max) * 100
        highPercent = 100.0

        lowIndex = int((lowPercent / 100) * data_max)
        highIndex = int((highPercent / 100) * data_max)


        range_array = numpy.arange(0, data_max + 1, dtype=numpy.float32)
        lut = (((range_array - lowIndex) * data_max) / (highIndex - lowIndex))  # floating point math, results in negative numbers

        lut[lut < 0] = 0  # clip low end
        lut[lut > data_max] = data_max  # clip high end

        lut = lut.astype(numpy_dtype)  # this must come after clipping


        # apply lookup table
        stretched_image = lut.take(data, mode='raise')

        levels_elapsed_s = time.time() - levels_start
        logger.info('Image levels in %0.4f s', levels_elapsed_s)


        return stretched_image


    def _get_image_stddev(self, data):
        mean_std_start = time.time()


        # mask arrays allow using the detection mask to perform calculations on
        # arbitrary boundaries in the image
        if len(data.shape) == 2:
            ma = numpy.ma.masked_array(data, mask=self._numpy_mask)

            # mono
            mean = numpy.ma.mean(ma)
            stddev = numpy.ma.std(ma)
        else:
            # color
            b_ma = numpy.ma.masked_array(data[:, :, 0], mask=self._numpy_mask)
            g_ma = numpy.ma.masked_array(data[:, :, 1], mask=self._numpy_mask)
            r_ma = numpy.ma.masked_array(data[:, :, 2], mask=self._numpy_mask)

            b_mean = numpy.ma.mean(b_ma)
            g_mean = numpy.ma.mean(g_ma)
            r_mean = numpy.ma.mean(r_ma)

            b_stddev = numpy.ma.std(b_ma)
            g_stddev = numpy.ma.std(g_ma)
            r_stddev = numpy.ma.std(r_ma)

            mean = (b_mean + g_mean + r_mean) / 3
            stddev = (b_stddev + g_stddev + r_stddev) / 3


        mean_std_elapsed_s = time.time() - mean_std_start
        logger.info('Mean and std dev in %0.4f s', mean_std_elapsed_s)

        return mean, stddev


    def _generateNumpyMask(self, img):
        if isinstance(self._sqm_mask, type(None)):
            logger.info('Generating mask based on SQM_ROI')

            image_height, image_width = img.shape[:2]

            mask = numpy.full((image_height, image_width), True, dtype=numpy.bool_)

            sqm_roi = self.config.get('SQM_ROI', [])

            try:
                x1 = int(sqm_roi[0] / self.bin_v.value)
                y1 = int(sqm_roi[1] / self.bin_v.value)
                x2 = int(sqm_roi[2] / self.bin_v.value)
                y2 = int(sqm_roi[3] / self.bin_v.value)
            except IndexError:
                logger.warning('Using central ROI for blob calculations')
                sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
                x1 = int((image_width / 2) - (image_width / sqm_fov_div))
                y1 = int((image_height / 2) - (image_height / sqm_fov_div))
                x2 = int((image_width / 2) + (image_width / sqm_fov_div))
                y2 = int((image_height / 2) + (image_height / sqm_fov_div))


            # True values will be masked
            mask[y1:y2, x1:x2] = False

        else:
            # True values will be masked
            mask = self._sqm_mask == 0


        self._numpy_mask = mask

