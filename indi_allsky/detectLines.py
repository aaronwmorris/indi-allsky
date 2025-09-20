import time
import cv2
import numpy
import logging


logger = logging.getLogger('indi_allsky')



class IndiAllskyDetectLines(object):

    canny_low_threshold = 15
    canny_high_threshold = 50

    blur_kernel_size = 5

    rho = 1  # distance resolution in pixels of the Hough grid
    theta = numpy.pi / 180  # angular resolution in radians of the Hough grid
    threshold = 125  # minimum number of votes (intersections in Hough grid cell)
    min_line_length = 40  # minimum number of pixels making up a line
    max_line_gap = 20  # maximum gap in pixels between connectable line segments

    mask_blur_kernel_size = 75


    def __init__(self, config, bin_v, mask=None):
        self.config = config
        self.bin_v = bin_v

        self._sqm_mask = mask
        self._sqm_gradient_mask = None


    def detectLines(self, original_img):
        if isinstance(self._sqm_mask, type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateSqmMask(original_img)

        if isinstance(self._sqm_gradient_mask, type(None)):
            # This only needs to be done once
            self._generateSqmGradientMask(original_img)


        # apply the gradient to the image
        masked_img = (original_img * self._sqm_gradient_mask).astype(numpy.uint8)

        #cv2.imwrite('/tmp/masked.jpg', masked_img, [cv2.IMWRITE_JPEG_QUALITY, 90])  # debugging


        if len(original_img.shape) == 2:
            img_gray = masked_img
        else:
            img_gray = cv2.cvtColor(masked_img, cv2.COLOR_BGR2GRAY)



        lines_start = time.time()

        blur_gray = cv2.GaussianBlur(img_gray, (self.blur_kernel_size, self.blur_kernel_size), cv2.BORDER_DEFAULT)


        edges = cv2.Canny(blur_gray, self.canny_low_threshold, self.canny_high_threshold)

        # Run Hough on edge detected image
        # Output "lines" is an array containing endpoints of detected line segments
        lines = cv2.HoughLinesP(
            edges,
            self.rho,
            self.theta,
            self.threshold,
            numpy.array([]),
            self.min_line_length,
            self.max_line_gap,
        )


        lines_elapsed_s = time.time() - lines_start

        if isinstance(lines, type(None)):
            logger.info('Detected 0 lines in %0.4f s', lines_elapsed_s)
            return list()

        logger.info('Detected %d lines in %0.4f s', len(lines), lines_elapsed_s)


        self._drawLines(original_img, lines)

        return lines


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
            logger.warning('Using central ROI for blob calculations')
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
            color=255,  # mono
            thickness=cv2.FILLED,
        )

        # mask needs to be blurred so that we do not detect it as an edge
        self._sqm_mask = mask


    def _generateSqmGradientMask(self, img):
        image_height, image_width = img.shape[:2]

        if self.config.get('IMAGE_STACK_COUNT', 1) > 1 and self.config.get('IMAGE_STACK_SPLIT'):
            # mask center line split between panes
            half_width = int(image_width / 2)
            cv2.line(
                img=self._sqm_mask,
                pt1=(half_width, 0),
                pt2=(half_width, image_height),
                color=0,  # mono
                thickness=71,
            )

        # blur the mask to prevent mask edges from being detected as lines
        blur_mask = cv2.blur(self._sqm_mask, (self.mask_blur_kernel_size, self.mask_blur_kernel_size), cv2.BORDER_DEFAULT)

        if len(img.shape) == 2:
            # mono
            mask = blur_mask
        else:
            # color
            mask = cv2.cvtColor(blur_mask, cv2.COLOR_GRAY2BGR)

        self._sqm_gradient_mask = (mask / 255).astype(numpy.float32)


    def _drawLines(self, img, lines):
        if not self.config.get('DETECT_DRAW'):
            return

        color_bgr = list(self.config['TEXT_PROPERTIES']['FONT_COLOR'])
        color_bgr.reverse()


        for line in lines:
            for x1, y1, x2, y2 in line:
                cv2.line(
                    img,
                    (x1, y1),
                    (x2, y2),
                    tuple(color_bgr),
                    3,
                )

