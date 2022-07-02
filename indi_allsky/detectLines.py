import time
import tempfile
import shutil
import cv2
import numpy
from pathlib import Path
import logging


logger = logging.getLogger('indi_allsky')



class IndiAllskyDetectLines(object):

    canny_low_threshold = 50
    canny_high_threshold = 150

    blur_kernel_size = 5

    rho = 1  # distance resolution in pixels of the Hough grid
    theta = numpy.pi / 180  # angular resolution in radians of the Hough grid
    threshold = 15  # minimum number of votes (intersections in Hough grid cell)
    min_line_length = 50  # minimum number of pixels making up a line
    max_line_gap = 20  # maximum gap in pixels between connectable line segments

    def __init__(self, config):
        self.config = config

        self.x_offset = 0
        self.y_offset = 0

        if self.config['IMAGE_FOLDER']:
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()


    def detectLines(self, img):
        image_height, image_width = img.shape[:2]

        sqm_roi = self.config.get('SQM_ROI', [])

        try:
            x1, y1, x2, y2 = sqm_roi
        except ValueError:
            logger.warning('Using central ROI for line detection')
            x1 = int((image_width / 2) - (image_width / 3))
            y1 = int((image_height / 2) - (image_height / 3))
            x2 = int((image_width / 2) + (image_width / 3))
            y2 = int((image_height / 2) + (image_height / 3))


        self.x_offset = x1
        self.y_offset = y1

        roi_img = img[
            y1:y2,
            x1:x2,
        ]

        if len(img.shape) == 2:
            img_gray = roi_img
        else:
            img_gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)



        lines_start = time.time()

        blur_gray = cv2.GaussianBlur(img_gray, (self.blur_kernel_size, self.blur_kernel_size), 0)


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
        logger.info('Line detection in %0.4f s', lines_elapsed_s)

        if isinstance(lines, type(None)):
            logger.info('Detected 0 lines')
            return list()


        logger.info('Detected %d lines', len(lines))

        self._drawLines(img, lines, (x1, y1, x2, y2))

        return lines


    def _drawLines(self, img, lines, box):
        line_image = img.copy()

        logger.info('Draw box around ROI')
        cv2.rectangle(
            img=line_image,
            pt1=(box[0], box[1]),
            pt2=(box[2], box[3]),
            color=(128, 128, 128),
            thickness=1,
        )


        for line in lines:
            for x1, y1, x2, y2 in line:
                cv2.line(
                    line_image,
                    (x1 + self.x_offset, y1 + self.y_offset),
                    (x2 + self.x_offset, y2 + self.y_offset),
                    (255, 0, 0),
                    3,
                )


        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.jpg')
        f_tmpfile.close()

        tmpfile_name = Path(f_tmpfile.name)
        tmpfile_name.unlink()  # remove tempfile, will be reused below


        cv2.imwrite(str(tmpfile_name), line_image, [cv2.IMWRITE_JPEG_QUALITY, self.config['IMAGE_FILE_COMPRESSION']['jpg']])

        lines_file = self.image_dir.joinpath('lines.jpg')

        shutil.copy2(f_tmpfile.name, str(lines_file))  # copy file in place
        lines_file.chmod(0o644)

        tmpfile_name.unlink()  # cleanup

