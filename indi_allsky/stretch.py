
import time
import numpy
import logging


logger = logging.getLogger('indi_allsky')


class IndiAllSkyStretch(object):

    def __init__(self, config, night_v, moonmode_v):
        self.config = config

        self.night_v = night_v
        self.moonmode_v = moonmode_v


    def main(self, data, image_bit_depth):
        if not self.night_v.value:
            # No daytime stretching
            return data


        if self.moonmode_v.value:
            logger.info('Moon mode stretching disabled')
            return data


        if self.config.get('IMAGE_STRETCH', {}).get('MODE1_ENABLE'):
            logger.info('Using image stretch mode 1')
            return self.mode1_stretch(data, image_bit_depth)
        else:
            logger.info('Image stretching disabled')
            return data


    def mode1_stretch(self, data, image_bit_depth):

        data = self.mode1_apply_gamma(data, image_bit_depth)

        data = self.mode1_adjustImageLevels(data, image_bit_depth)

        return data


    def mode1_apply_gamma(self, data, image_bit_depth):
        gamma = self.config.get('IMAGE_STRETCH', {}).get('MODE1_GAMMA', 3.0)

        if not gamma:
            return data

        logger.info('Applying gamma correction')

        gamma_start = time.time()

        if image_bit_depth == 8:
            data_max = 256
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)
            lut = (((range_array / data_max) ** (1 / float(gamma))) * data_max).astype(numpy.uint8)
        else:
            data_max = 2 ** image_bit_depth
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)
            lut = (((range_array / data_max) ** (1 / float(gamma))) * data_max).astype(numpy.uint16)


        gamma_data = lut.take(data, mode='raise')

        gamma_elapsed_s = time.time() - gamma_start
        logger.info('Image gamma in %0.4f s', gamma_elapsed_s)

        return gamma_data


    def mode1_adjustImageLevels(self, data, image_bit_depth):
        stddevs = self.config.get('IMAGE_STRETCH', {}).get('MODE1_STDDEVS', 3.0)

        mean, stddev = self._get_image_stddev(data)
        logger.info('Mean: %0.2f, StdDev: %0.2f', mean, stddev)


        levels_start = time.time()

        data_max = 2 ** image_bit_depth

        low = int(mean - (stddevs * stddev))

        lowPercent  = (low / data_max) * 100
        highPercent = 100.0

        lowIndex = int((lowPercent / 100) * data_max)
        highIndex = int((highPercent / 100) * data_max)


        if image_bit_depth == 8:
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)

            #range_array[range_array <= lowIndex] = 0
            #range_array[range_array > data_max] = data_max

            lut = (((range_array - lowIndex) * data_max) / (highIndex - lowIndex))  # floating point match, results in negative numbers
            lut[lut < 0] = 0
            lut[lut > data_max] = data_max
            lut = lut.astype(numpy.uint8)
        else:
            range_array = numpy.arange(0, data_max, dtype=numpy.float32)

            #range_array[range_array <= lowIndex] = 0
            #range_array[range_array > highIndex] = data_max

            lut = (((range_array - lowIndex) * data_max) / (highIndex - lowIndex))  # floating point match, results in negative numbers
            lut[lut < 0] = 0
            lut[lut > data_max] = data_max
            lut = lut.astype(numpy.uint16)


        stretch_image = lut.take(data, mode='raise')

        levels_elapsed_s = time.time() - levels_start
        logger.info('Image levels in %0.4f s', levels_elapsed_s)


        return stretch_image


    def _get_image_stddev(self, data):
        mean_std_start = time.time()


        image_height, image_width = data.shape[:2]

        x1 = int((image_width / 2) - (image_width / 4))
        y1 = int((image_height / 2) - (image_height / 4))
        x2 = int((image_width / 2) + (image_width / 4))
        y2 = int((image_height / 2) + (image_height / 4))

        roi = data[
            y1:y2,
            x1:x2,
        ]


        if len(roi.shape) == 2:
            # mono
            mean = numpy.mean(roi)
            stddev = numpy.std(roi)
        else:
            # color
            b, g, r = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]

            b_mean = numpy.mean(b)
            g_mean = numpy.mean(g)
            r_mean = numpy.mean(r)

            b_stddev = numpy.std(b)
            g_stddev = numpy.std(g)
            r_stddev = numpy.std(r)

            mean = (b_mean + g_mean + r_mean) / 3
            stddev = (b_stddev + g_stddev + r_stddev) / 3


        mean_std_elapsed_s = time.time() - mean_std_start
        logger.info('Mean and std dev in %0.4f s', mean_std_elapsed_s)

        return mean, stddev


