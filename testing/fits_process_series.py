#!/usr/bin/env python3

###
### Processes FITS files using the indi-allsky processing pipeline
###


import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
import logging

import cv2
from PIL import Image

from multiprocessing import Value
from multiprocessing import Array
from astropy.io import fits
from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig

from indi_allsky.processing import ImageProcessor
from indi_allsky.flask.models import IndiAllSkyDbCameraTable

# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)


class ProcessFitsSeries(object):

    image_type = 'jpg'
    jpeg_quality = 90


    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config

        self._camera_id = None
        self._input_dir = None
        self._output_dir = None


    @property
    def camera_id(self):
        return self._camera_id

    @camera_id.setter
    def camera_id(self, new_camera_id):
        self._camera_id = int(new_camera_id)


    @property
    def input_dir(self):
        return self._input_dir

    @input_dir.setter
    def input_dir(self, new_input_dir):
        self._input_dir = Path(str(new_input_dir))


    @property
    def output_dir(self):
        return self._output_dir

    @output_dir.setter
    def output_dir(self, new_output_dir):
        self._output_dir = Path(str(new_output_dir))


    def main(self):

        camera = self.getCameraById(self.camera_id)


        ### Find the FITS files
        fits_file_list = list()
        self.getFolderFilesByExt(self.input_dir, fits_file_list)

        # Exclude empty files
        fits_file_list_nonzero = filter(lambda p: p.stat().st_size != 0, fits_file_list)

        # Sort by timestamp
        fits_file_list_ordered = sorted(fits_file_list_nonzero, key=lambda p: p.stat().st_mtime)

        logger.warning('Found %d files for processing', len(fits_file_list_ordered))


        ### Start processing
        position_av = Array('f', [
            camera.latitude,
            camera.longitude,
            camera.elevation,
        ])


        gain_v = Value('i', 0)
        bin_v = Value('i', 1)
        sensors_temp_av = Array('f', [0])
        sensors_user_av = Array('f', [0])
        night_v = Value('i', 1)  # using night values for processing
        moonmode_v = Value('i', 0)


        image_processor = ImageProcessor(
            self.config,
            position_av,
            gain_v,
            bin_v,
            sensors_temp_av,
            sensors_user_av,
            night_v,
            moonmode_v,
            {},    # astrometric_data
        )


        for filename_p in fits_file_list_ordered:
            logger.warning('Processing %s', filename_p)

            exp_ts = filename_p.stat().st_mtime
            exp_date = datetime.fromtimestamp(exp_ts)


            try:
                hdulist = fits.open(filename_p)
            except OSError as e:
                logger.error('Error: %s', str(e))
                continue


            exposure = float(hdulist[0].header['EXPTIME'])


            with gain_v.get_lock():
                gain_v.value = int(hdulist[0].header['GAIN'])

            with bin_v.get_lock():
                bin_v.value = int(hdulist[0].header.get('XBINNING', 1))

            with sensors_temp_av.get_lock():
                sensors_temp_av[0] = float(hdulist[0].header.get('CCD-TEMP', 0))

            with sensors_user_av.get_lock():
                sensors_user_av[0] = float(hdulist[0].header.get('CCD-TEMP', 0))

            with night_v.get_lock():
                night_v.value = 1


            hdulist.close()


            image_processor.add(filename_p, exposure, exp_date, 0.0, camera)

            # Calibration is usually already applied to FITS
            #image_processor.calibrate()

            image_processor.debayer()

            image_processor.stack()  # this populates self.image

            image_processor.stretch()


            if self.config['NIGHT_CONTRAST_ENHANCE']:
                if self.config.get('CONTRAST_ENHANCE_16BIT'):
                    image_processor.contrast_clahe_16bit()


            image_processor.convert_16bit_to_8bit()


            # rotation
            image_processor.rotate_90()
            image_processor.rotate_angle()


            # verticle flip
            image_processor.flip_v()

            # horizontal flip
            image_processor.flip_h()


            # green removal
            image_processor.scnr()


            # white balance
            image_processor.white_balance_manual_bgr()
            image_processor.white_balance_auto_bgr()


            # saturation
            image_processor.saturation_adjust()


            if self.config['NIGHT_CONTRAST_ENHANCE']:
                if not self.config.get('CONTRAST_ENHANCE_16BIT'):
                    image_processor.contrast_clahe()


            image_processor.colorize()

            image_processor.apply_image_circle_mask()

            #image_processor.apply_logo_overlay()


            image_processor.scale_image()


            #image_processor.orb_image()

            #image_processor.cardinal_dirs_label()

            #image_processor.label_image()



            ### Save the image
            img = Image.fromarray(cv2.cvtColor(image_processor.image, cv2.COLOR_BGR2RGB))


            rel_p = filename_p.relative_to(self.input_dir)
            image_p = self.output_dir.joinpath(rel_p.parent, '{0:s}.{1:s}'.format(filename_p.stem, self.image_type))


            logger.warning('Saving %s', image_p)
            if not image_p.parent.is_dir():
                image_p.parent.mkdir(parents=True)

            img.save(str(image_p), quality=self.jpeg_quality)

            # set original file mtime
            os.utime(str(image_p), (exp_ts, exp_ts))


    def getCameraById(self, camera_id):
        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()

        return camera


    def getFolderFilesByExt(self, folder, file_list, extension_list=['fit', 'fits']):
        logger.info('Searching for image files in %s', folder)

        dot_extension_list = ['.{0:s}'.format(e) for e in extension_list]

        for item in Path(folder).iterdir():
            if item.is_file() and item.suffix in dot_extension_list:
                file_list.append(item)
            elif item.is_dir():
                self.getFolderFilesByExt(item, file_list, extension_list=extension_list)  # recursion



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'input_dir',
        help='Input directory',
        type=str,
    )
    argparser.add_argument(
        '--output_dir',
        '-o',
        help='Output directory',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--camera_id',
        help='Camera ID',
        type=int,
        default=1,
    )


    args = argparser.parse_args()


    pfs = ProcessFitsSeries()

    pfs.camera_id = args.camera_id
    pfs.input_dir = args.input_dir
    pfs.output_dir = args.output_dir

    pfs.main()

