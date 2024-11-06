import numpy
import cv2
import PIL
from PIL import Image
import logging

from .preProcessorBase import PreProcessorBase


logger = logging.getLogger('indi_allsky')


class PreProcessorWrapKeogram(PreProcessorBase):

    def __init__(self, *args, **kwargs):
        super(PreProcessorWrapKeogram, self).__init__(*args, **kwargs)

        self._keogram_image = None

        self.image_count = 0

        self.image_circle = self.config.get('TIMELAPSE', {}).get('IMAGE_CIRCLE', 2000)
        self.keogram_ratio = self.config.get('TIMELAPSE', {}).get('KEOGRAM_RATIO', 0.15)
        self.offset_x = self.config.get('LENS_OFFSET_X', 0)
        self.offset_y = self.config.get('LENS_OFFSET_Y', 0)


    def main(self, file_list):
        with Image.open(str(self.keogram)) as k_img:
            self._keogram_image = cv2.cvtColor(numpy.array(k_img), cv2.COLOR_RGB2BGR)


        keogram_height, keogram_width = self._keogram_image.shape[:2]

        k_ratio_height = keogram_height / self.image_circle
        if k_ratio_height > self.keogram_ratio:
            # resize keogram
            new_k_height = int(self.image_circle * self.keogram_ratio)
            self._keogram_image = cv2.resize(self._keogram_image, (keogram_width, new_k_height), interpolation=cv2.INTER_AREA)
            keogram_height = new_k_height


        # flip upside down and backwards
        self._keogram_image = cv2.flip(self._keogram_image, -1)


        for i, f in enumerate(file_list):
            # the symlink files must start at index 0 or ffmpeg will fail
            self.wrap(i, f, self.seqfolder)


    def wrap(self, i, f, seqfolder_p):
        keogram = self._keogram_image.copy()
        keogram_height, keogram_width = keogram.shape[:2]

        current_percent = i / self.file_list_ordered_len

        #keogram_line = int(keogram_width * current_percent)
        keogram_line = int(keogram_width * (1 - current_percent))  # backwards
        #logger.info('Line: %d', keogram_line)

        line = numpy.full([keogram_height, 1, 3], 255, dtype=numpy.uint8)
        keogram[0:keogram_height, keogram_line:keogram_line + 1] = line


        try:
            with Image.open(str(f)) as img:
                image = cv2.cvtColor(numpy.array(img), cv2.COLOR_RGB2BGR)
        except PIL.UnidentifiedImageError:
            logger.error('Unable to read %s', f)
            return


        image_height, image_width = image.shape[:2]
        #logger.info('Image: %d x %d', image_width, image_height)


        if image_width < (self.image_circle + (keogram_height * 2) + abs(self.offset_x)):
            final_width = self.image_circle + (keogram_height * 2) + abs(self.offset_x)
        else:
            final_width = image_width

        if image_height < (self.image_circle + (keogram_height * 2) + abs(self.offset_y)):
            final_height = self.image_circle + (keogram_height * 2) + abs(self.offset_y)
        else:
            final_height = image_height

        #logger.info('Final: %d x %d', final_width, final_height)


        # add black area at the top of the keogram to wrap around center
        d_keogram = numpy.zeros([int((self.image_circle + keogram_height) / 2), keogram_width, 3], dtype=numpy.uint8)
        d_height, d_width = d_keogram.shape[:2]
        d_keogram[d_height - keogram_height:d_height, 0:keogram_width] = keogram


        # add alpha channel for transparency (black area)
        d_keogram_alpha = numpy.zeros([d_height, d_width], dtype=numpy.uint8)
        d_keogram_alpha[d_height - keogram_height:d_height, 0:keogram_width] = 255
        d_keogram = numpy.dstack((d_keogram, d_keogram_alpha))


        d_image = cv2.rotate(d_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)


        # wrap the keogram
        wrapped_height, wrapped_width = self.image_circle + (keogram_height * 2) + abs(self.offset_x), self.image_circle + (keogram_height * 2) + abs(self.offset_y)  # reversed offsets due to rotation below
        wrapped_keogram = cv2.warpPolar(
            d_image,
            (wrapped_width, wrapped_height),
            (int(wrapped_height / 2), int(wrapped_height / 2)),
            int(wrapped_height / 2),
            cv2.WARP_INVERSE_MAP,
        )

        #wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_COUNTERCLOCKWISE)  # start keogram at top
        wrapped_keogram = cv2.rotate(wrapped_keogram, cv2.ROTATE_90_CLOCKWISE)  # start keogram at bottom


        # separate layers
        wrapped_keogram_bgr = wrapped_keogram[:, :, :3]
        wrapped_keogram_alpha = (wrapped_keogram[:, :, 3] / 255).astype(numpy.float32)

        # create alpha mask
        alpha_mask = numpy.dstack((
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
            wrapped_keogram_alpha,
        ))


        f_image = numpy.zeros([final_height, final_width, 3], dtype=numpy.uint8)
        f_image[
            int((final_height / 2) - (image_height / 2) + self.offset_y):int((final_height / 2) + (image_height / 2) + self.offset_y),
            int((final_width / 2) - (image_width / 2) - self.offset_x):int((final_width / 2) + (image_width / 2) - self.offset_x),
        ] = image  # recenter the image circle in the new image


        # apply alpha mask
        image_with_keogram = (f_image * (1 - alpha_mask) + wrapped_keogram_bgr * alpha_mask).astype(numpy.uint8)


        mod_height = final_height % 2
        mod_width = final_width % 2

        if mod_height or mod_width:
            # width and height needs to be divisible by 2 for timelapse
            crop_width = final_width - mod_width
            crop_height = final_height - mod_height

            image_with_keogram = image_with_keogram[
                0::crop_height,
                0:crop_width,
            ]



        outfile_p = seqfolder_p.joinpath('{0:05d}.{1:s}'.format(self.image_count, self.config['IMAGE_FILE_TYPE']))
        if self.config['IMAGE_FILE_TYPE'] in ('jpg', 'jpeg'):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=self.config['IMAGE_FILE_COMPRESSION']['jpg'])
        elif self.config['IMAGE_FILE_TYPE'] in ('png',):
            #img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            #img_rgb.save(str(f_tmp_frame_p), compress_level=self.config['IMAGE_FILE_COMPRESSION']['png'])

            # opencv is faster than Pillow with PNG
            cv2.imwrite(str(outfile_p), self.trail_image, [cv2.IMWRITE_PNG_COMPRESSION, self.config['IMAGE_FILE_COMPRESSION']['png']])
        elif self.config['IMAGE_FILE_TYPE'] in ('webp',):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), quality=90, lossless=False)
        elif self.config['IMAGE_FILE_TYPE'] in ('tif', 'tiff'):
            img_rgb = Image.fromarray(cv2.cvtColor(self.trail_image, cv2.COLOR_BGR2RGB))
            img_rgb.save(str(outfile_p), compression='tiff_lzw')
        else:
            raise Exception('Unknown file type: %s', self.config['IMAGE_FILE_TYPE'])


        self.image_count += 1

