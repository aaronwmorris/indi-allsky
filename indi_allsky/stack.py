import time
import numpy
import cv2
import astroalign
import logging

logger = logging.getLogger('indi_allsky')


class IndiAllskyStacker(object):

    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._sqm_mask = mask

        self._detection_sigma = 5
        self._max_control_points = 50
        self._min_area = 10

        self.hist_rotation = list()
        self._rotation_dev = 3  # rotation may not exceed this deviation
        self._history_min_vals = 15


    @property
    def detection_sigma(self):
        return self._detection_sigma

    @detection_sigma.setter
    def detection_sigma(self, new_detection_sigma):
        self._detection_simga = int(new_detection_sigma)


    @property
    def max_control_points(self):
        return self._max_control_points

    @max_control_points.setter
    def max_control_points(self, new_max_control_points):
        self._max_control_points = int(new_max_control_points)


    @property
    def min_area(self):
        return self._min_area

    @min_area.setter
    def min_area(self, new_min_area):
        self._min_area = int(new_min_area)


    @property
    def MIN_MATCHES_FRACTION(self):
        # default 0.8
        return astroalign.MIN_MATCHES_FRACTION

    @MIN_MATCHES_FRACTION.setter
    def MIN_MATCHES_FRACTION(self, new_MIN_MATCHES_FRACTION):
        astroalign.MIN_MATCHES_FRACTION = float(new_MIN_MATCHES_FRACTION)


    @property
    def NUM_NEAREST_NEIGHBORS(self):
        # default 5
        return astroalign.NUM_NEAREST_NEIGHBORS

    @NUM_NEAREST_NEIGHBORS.setter
    def NUM_NEAREST_NEIGHBORS(self, new_NUM_NEAREST_NEIGHBORS):
        astroalign.NUM_NEAREST_NEIGHBORS = int(new_NUM_NEAREST_NEIGHBORS)


    @property
    def PIXEL_TOL(self):
        # default 2
        return astroalign.PIXEL_TOL

    @PIXEL_TOL.setter
    def PIXEL_TOL(self, new_PIXEL_TOL):
        astroalign.PIXEL_TOL = int(new_PIXEL_TOL)



    def mean(self, *args, **kwargs):
        # alias for average
        return self.average(*args, **kwargs)


    def average(self, stack_data_list, numpy_type):
        mean_image = numpy.mean(stack_data_list, axis=0)
        return mean_image.astype(numpy_type)  # no floats


    def maximum(self, stack_data_list, numpy_type):
        image_max = stack_data_list[0]  # start with first image

        # compare with remaining images
        for i in stack_data_list[1:]:
            image_max = numpy.maximum(image_max, i)

        return image_max.astype(numpy_type)

    def minimum(self, stack_data_list, numpy_type):
        image_min = stack_data_list[0]  # start with first image

        # compare with remaining images
        for i in stack_data_list[1:]:
            image_min = numpy.minimum(image_min, i)

        return image_min.astype(numpy_type)


    def register(self, stack_i_ref_list):
        # first image is the reference
        reference_i_ref = stack_i_ref_list[0]


        if isinstance(self._sqm_mask, type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateSqmMask(reference_i_ref.opencv_data)


        reg_data_list = [reference_i_ref.opencv_data]  # add target to final list

        #reference_masked = self._crop(reference_i_ref.opencv_data)
        reference_masked = cv2.bitwise_and(reference_i_ref.opencv_data, reference_i_ref.opencv_data, mask=self._sqm_mask)

        reg_start = time.time()


        last_rotation = 0

        for i_ref in stack_i_ref_list[1:]:
            #i_masked = self._crop(i_ref.opencv_data)
            i_masked = cv2.bitwise_and(i_ref.opencv_data, i_ref.opencv_data, mask=self._sqm_mask)

            # detection_sigma default = 5
            # max_control_points default = 50
            # min_area default = 5

            try:
                ### Find transform using a crop of the image
                transform, (source_list, target_list) = astroalign.find_transform(
                    i_masked,
                    reference_masked,
                    detection_sigma=self.detection_sigma,
                    max_control_points=self.max_control_points,
                    min_area=self.min_area,
                )

                logger.info(
                    'Registration Matches: %d, Rotation: %0.6f, Translation: (%0.6f, %0.6f), Scale: %0.6f',
                    len(target_list),
                    transform.rotation,
                    transform.translation[0], transform.translation[1],
                    transform.scale,
                )


                # add new rotation value
                rotation = transform.rotation - last_rotation
                #logger.info('Last rotation: %0.8f', rotation)


                if len(self.hist_rotation) >= self._history_min_vals:
                    # need at least this many values to establish an average
                    rotation_mean = numpy.mean(self.hist_rotation)
                    rotation_std = numpy.std(self.hist_rotation)

                    #logger.info('Rotation standard deviation: %0.8f', rotation_std)

                    rotation_stddev_limit = rotation_std * self._rotation_dev


                    # if the new rotation exceeds the deviation limit, do not apply the transform
                    if rotation > (rotation_mean + rotation_stddev_limit)\
                            or rotation < (rotation_mean - rotation_stddev_limit):

                        logger.error('Rotation exceeded limit of +/- %0.8f', rotation_stddev_limit)
                        last_rotation += rotation_mean  # skipping a frame, need to account for rotation difference
                        continue


                self.hist_rotation.append(rotation)  # only add known good rotation values
                last_rotation = transform.rotation



                reg_data, footprint = astroalign.apply_transform(
                    transform,
                    i_ref.opencv_data,
                    reference_i_ref.opencv_data,
                )

                ### Register full image
                #reg_data, footprint = astroalign.register(
                #    i_ref.opencv_data,
                #    reference_i_ref.opencv_data,
                #    detection_sigma=self.detection_simga,
                #    max_control_points=self.max_control_points,
                #    min_area=self.min_area,
                #)
            except astroalign.MaxIterError as e:
                logger.error('Image registration failure: %s', str(e))
                continue
            except ValueError as e:
                logger.error('Image registration failure: %s', str(e))
                continue

            reg_data_list.append(reg_data)


        reg_elapsed_s = time.time() - reg_start
        logger.info('Registered %d+1 images in %0.4f s', len(stack_i_ref_list) - 1, reg_elapsed_s)  # reference image is not aligned

        return reg_data_list


    def _crop(self, image):
        image_height, image_width = image.shape[:2]

        x1 = int((image_width / 2) - (image_width / 4))
        y1 = int((image_height / 2) - (image_height / 4))
        x2 = int((image_width / 2) + (image_width / 4))
        y2 = int((image_height / 2) + (image_height / 4))


        return image[
            y1:y2,
            x1:x2,
        ]


    def _generateSqmMask(self, img):
        logger.info('Generating mask based on SQM_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1 = int(sqm_roi[0] / self.bin_v.value)
            y1 = int(sqm_roi[1] / self.bin_v.value)
            x2 = int(sqm_roi[2] / self.bin_v.value)
            y2 = int(sqm_roi[3] / self.bin_v.value)
        except IndexError:
            logger.warning('Using central ROI for registration')
            sqm_fov_div = self.config.get('SQM_FOV_DIV', 4)
            x1 = int((image_width / 2) - (image_width / sqm_fov_div))
            y1 = int((image_height / 2) - (image_height / sqm_fov_div))
            x2 = int((image_width / 2) + (image_width / sqm_fov_div))
            y2 = int((image_height / 2) + (image_height / sqm_fov_div))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )

        self._sqm_mask = mask


