### This is a mini image processor for masks
### Masks are pre-rotation/flip/cropping and need these operations to be applied to processed images

#import time
import cv2
import logging


logger = logging.getLogger('indi_allsky')


class MaskProcessor(object):
    def __init__(
        self,
        config,
        bin_v,
    ):

        self.config = config
        self.bin_v = bin_v

        self._image = None


    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, new_image):
        self._image = new_image


    def rotate_90(self):
        try:
            rotate_enum = getattr(cv2, self.config['IMAGE_ROTATE'])
        except AttributeError:
            logger.error('Unknown rotation option: %s', self.config['IMAGE_ROTATE'])
            return

        self.image = cv2.rotate(self.image, rotate_enum)


    def rotate_angle(self):
        angle = self.config.get('IMAGE_ROTATE_ANGLE')
        keep_size = self.config.get('IMAGE_ROTATE_KEEP_SIZE')

        #rotate_start = time.time()

        height, width = self.image.shape[:2]
        center_x = int(width / 2)
        center_y = int(height / 2)


        rot = cv2.getRotationMatrix2D((center_x, center_y), int(angle), 1.0)


        if keep_size:
            bound_w = width
            bound_h = height
        else:
            abs_cos = abs(rot[0, 0])
            abs_sin = abs(rot[0, 1])

            bound_w = int(height * abs_sin + width * abs_cos)
            bound_h = int(height * abs_cos + width * abs_sin)


        rot[0, 2] += (bound_w / 2) - center_x
        rot[1, 2] += (bound_h / 2) - center_y


        self.image = cv2.warpAffine(self.image, rot, (bound_w, bound_h))

        rot_height, rot_width = self.image.shape[:2]
        mod_height = rot_height % 2
        mod_width = rot_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_height = rot_height - mod_height
            crop_width = rot_width - mod_width

            self.image = self.image[
                0:crop_height,
                0:crop_width,
            ]


        #processing_elapsed_s = time.time() - rotate_start
        #logger.warning('Rotation in %0.4f s', processing_elapsed_s)


    def _flip(self, data, cv2_axis):
        return cv2.flip(data, cv2_axis)


    def flip_v(self):
        self.image = self._flip(self.image, 0)


    def flip_h(self):
        self.image = self._flip(self.image, 1)


    def crop_image(self):
        # divide the coordinates by binning value
        x1 = int(self.config['IMAGE_CROP_ROI'][0] / self.bin_v.value)
        y1 = int(self.config['IMAGE_CROP_ROI'][1] / self.bin_v.value)
        x2 = int(self.config['IMAGE_CROP_ROI'][2] / self.bin_v.value)
        y2 = int(self.config['IMAGE_CROP_ROI'][3] / self.bin_v.value)


        self.image = self.image[
            y1:y2,
            x1:x2,
        ]

        #new_height, new_width = self.image.shape[:2]
        #logger.info('New cropped size: %d x %d', new_width, new_height)


    def scale_image(self):
        image_height, image_width = self.image.shape[:2]

        logger.info('Scaling mask by %d%%', self.config['IMAGE_SCALE'])
        new_height = int(image_height * self.config['IMAGE_SCALE'] / 100.0)
        new_width = int(image_width * self.config['IMAGE_SCALE'] / 100.0)

        # ensure size is divisible by 2
        new_height = new_height - (new_height % 2)
        new_width = new_width - (new_width % 2)

        logger.info('New size: %d x %d', new_width, new_height)

        self.image = cv2.resize(self.image, (new_width, new_height), interpolation=cv2.INTER_AREA)

