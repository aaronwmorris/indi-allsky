import sys
import io
import time
import math
import tempfile
import json
import shutil
from datetime import datetime
from pathlib import Path
import logging

import numpy
from astropy.io import fits

import ccdproc
from astropy.stats import mad_std

from sqlalchemy.orm.exc import NoResultFound

from multiprocessing import Queue
from multiprocessing import Value


from .indi import IndiClient

from .flask import db
from .flask.miscDb import miscDb

from .flask.models import IndiAllSkyDbDarkFrameTable


logger = logging.getLogger('indi_allsky')


class IndiAllSkyDarks(object):
    def __init__(self, f_config):
        self.config = json.loads(f_config.read())
        f_config.close()

        self._count = 10

        self.image_q = Queue()
        self.indiclient = None
        self.ccdDevice = None
        self.camera_id = None
        self.exposure_v = Value('f', -1.0)
        self.gain_v = Value('i', -1)  # value set in CCD config
        self.bin_v = Value('i', 1)  # set 1 for sane default
        self.sensortemp_v = Value('f', 0)

        self._miscDb = miscDb(self.config)

        self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        self.darks_dir = self.image_dir.joinpath('darks')


    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, new_count):
        logger.info('Changing image count to %d', int(new_count))
        self._count = int(new_count)



    def _initialize(self):
        # instantiate the client
        self.indiclient = IndiClient(
            self.config,
            self.image_q,
            self.gain_v,
            self.bin_v,
            self.sensortemp_v,
        )

        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if (not(self.indiclient.connectServer())):
            logger.error("No indiserver running on %s:%d - Try to run", self.indiclient.getHost(), self.indiclient.getPort())
            logger.error("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)

        # give devices a chance to register
        time.sleep(8)

        # connect to all devices
        ccd_list = self.indiclient.findCcds()

        if len(ccd_list) == 0:
            logger.error('No CCDs detected')
            time.sleep(1)
            sys.exit(1)

        logger.info('Found %d CCDs', len(ccd_list))
        ccdDevice = ccd_list[0]

        logger.warning('Connecting to device %s', ccdDevice.getDeviceName())
        self.indiclient.connectDevice(ccdDevice.getDeviceName())
        self.ccdDevice = ccdDevice

        # set default device in indiclient
        self.indiclient.device = self.ccdDevice

        # add driver name to config
        self.config['CCD_NAME'] = self.ccdDevice.getDeviceName()
        self.config['CCD_SERVER'] = self.ccdDevice.getDriverExec()

        db_camera = self._miscDb.addCamera(self.config['CCD_NAME'])
        self.config['DB_CCD_ID'] = db_camera.id
        self.camera_id = db_camera.id


        # Disable debugging
        self.indiclient.disableDebug(self.ccdDevice)

        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode(self.ccdDevice)

        self.indiclient.configureDevice(self.ccdDevice, self.config['INDI_CONFIG_DEFAULTS'])
        self.indiclient.setFrameType(self.ccdDevice, 'FRAME_DARK')

        # get CCD information
        ccd_info = self.indiclient.getCcdInfo(self.ccdDevice)
        self.config['CCD_INFO'] = ccd_info


        # CFA/Debayer setting
        if not self.config.get('CFA_PATTERN'):
            self.config['CFA_PATTERN'] = self.config['CCD_INFO']['CCD_CFA']['CFA_TYPE'].get('text')

        logger.info('CCD CFA: {0:s}'.format(str(self.config['CFA_PATTERN'])))


        # Validate gain settings
        ccd_min_gain = self.config['CCD_INFO']['GAIN_INFO']['min']
        ccd_max_gain = self.config['CCD_INFO']['GAIN_INFO']['max']

        if self.config['CCD_CONFIG']['NIGHT']['GAIN'] < ccd_min_gain:
            logger.error('CCD night gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['NIGHT']['GAIN'] > ccd_max_gain:
            logger.error('CCD night gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['NIGHT']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['MOONMODE']['GAIN'] < ccd_min_gain:
            logger.error('CCD moon mode gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['MOONMODE']['GAIN'] > ccd_max_gain:
            logger.error('CCD moon mode gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['MOONMODE']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)

        if self.config['CCD_CONFIG']['DAY']['GAIN'] < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %d', int(ccd_min_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_min_gain)
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['GAIN'] > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %d', int(ccd_max_gain))
            self.config['CCD_CONFIG']['DAY']['GAIN'] = int(ccd_max_gain)
            time.sleep(3)


    def shoot(self, ccdDevice, exposure, sync=True, timeout=None):
        logger.info('Taking %0.8f s exposure (gain %d)', exposure, self.gain_v.value)

        ctl = self.indiclient.setCcdExposure(ccdDevice, exposure, sync=sync, timeout=timeout)

        return ctl


    def average(self):
        self._initialize()

        ccd_bits = int(self.config['CCD_INFO']['CCD_INFO']['CCD_BITSPERPIXEL']['current'])


        # exposures start with 1 and then every 5s until the max exposure
        dark_exposures = [1]
        dark_exposures.extend(list(range(5, math.ceil(self.config['CCD_EXPOSURE_MAX'] / 5) * 5, 5)))
        dark_exposures.append(math.ceil(self.config['CCD_EXPOSURE_MAX']))  # round up


        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        # 0  = ccd id
        # 1  = bits
        # 2  = exposure (seconds)
        # 3  = gain
        # 4  = binning
        # 5  = temperature
        # 6  = date
        # 7  = extension

        ### take darks

        ### NIGHT MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['BINNING'])


        for exposure in dark_exposures:
            self._take_average_exposures(exposure, dark_filename_t, ccd_bits)



        ### NIGHT MOON MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        ### take darks
        for exposure in dark_exposures:
            self._take_average_exposures(exposure, dark_filename_t, ccd_bits)



        ### DAY DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        ### take darks
        # day will rarely exceed 1 second
        for exposure in dark_exposures:
            self._take_average_exposures(exposure, dark_filename_t, ccd_bits)


    def _take_average_exposures(self, exposure, dark_filename_t, ccd_bits):
        self.indiclient.getCcdTemperature(self.ccdDevice)

        exp_date = datetime.now()
        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        filename = dark_filename_t.format(
            self.camera_id,
            ccd_bits,
            int(exposure),
            self.gain_v.value,
            self.bin_v.value,
            int(self.sensortemp_v.value),
            date_str,
        )


        image_list = list()
        image_bitpix = None
        hdulist = None

        for c in range(self._count):
            start = time.time()

            self.shoot(self.ccdDevice, float(exposure), sync=True)

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)


            hdulist = self._wait_for_image()
            image_bitpix = hdulist[0].header['BITPIX']

            image_list.append(hdulist[0].data)


        stacked_image = self._average_image(image_list, image_bitpix)
        #stacked_image = self._max_image(image_list, image_bitpix)

        # replace image data into original fit container
        hdulist[0].data = stacked_image

        self._write_dark(hdulist, filename, exposure)



    def _wait_for_image(self):
        i_dict = self.image_q.get(timeout=15)

        imgdata = i_dict['imgdata']
        #exposure = i_dict['exposure']
        #exp_date = i_dict['exp_date']
        #exp_elapsed = i_dict['exp_elapsed']
        #camera_id = i_dict['camera_id']
        #filename_t = i_dict.get('filename_t')
        #img_subdirs = i_dict.get('img_subdirs', [])  # we only use this for fits/darks



        ### OpenCV ###
        blobfile = io.BytesIO(imgdata)
        hdulist = fits.open(blobfile)

        return hdulist



    def _average_image(self, image_list, bitpix):
        if bitpix == 16:
            numpy_type = numpy.uint16
        elif bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')

        avg_image = numpy.average(image_list, axis=0)

        return numpy.ceil(avg_image).astype(numpy_type)


    def _max_image(self, image_list, bitpix):
        if bitpix == 16:
            numpy_type = numpy.uint16
        elif bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')


        image_height, image_width = image_list[0].shape[:2]
        max_image = numpy.zeros((image_height, image_width), dtype=numpy_type)

        for i in image_list:
            max_image = numpy.maximum(max_image, i)

        return max_image


    def _write_dark(self, hdulist, filename, exposure):
        filename_p = self.darks_dir.joinpath(filename)


        image_type = hdulist[0].header['IMAGETYP']
        image_bitpix = hdulist[0].header['BITPIX']

        logger.info('Detected image type: %s, bits: %d', image_type, image_bitpix)



        f_tmpfile = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.fit')

        hdulist.writeto(f_tmpfile)

        f_tmpfile.flush()
        f_tmpfile.close()


        file_dir = filename_p.parent
        if not file_dir.exists():
            file_dir.mkdir(mode=0o755, parents=True)

        logger.info('fit filename: %s', filename_p)


        try:
            dark_frame_entry = IndiAllSkyDbDarkFrameTable.query\
                .filter(IndiAllSkyDbDarkFrameTable.filename == str(filename_p))\
                .one()

            if filename_p.exists():
                logger.warning('Removing old dark frame: %s', filename_p)
                filename_p.unlink()

            db.session.delete(dark_frame_entry)
            db.session.commit()
        except NoResultFound:
            pass


        shutil.copy2(f_tmpfile.name, str(filename_p))  # copy file in place
        filename_p.chmod(0o644)


        self._miscDb.addDarkFrame(
            filename_p,
            self.camera_id,
            image_bitpix,
            exposure,
            self.gain_v.value,
            self.bin_v.value,
            self.sensortemp_v.value,
        )


        Path(f_tmpfile.name).unlink()  # delete temp file


    def sigma(self):
        self._initialize()

        ccd_bits = int(self.config['CCD_INFO']['CCD_INFO']['CCD_BITSPERPIXEL']['current'])


        # exposures start with 1 and then every 5s until the max exposure
        dark_exposures = [1]
        dark_exposures.extend(list(range(5, math.ceil(self.config['CCD_EXPOSURE_MAX'] / 5) * 5, 5)))
        dark_exposures.append(math.ceil(self.config['CCD_EXPOSURE_MAX']))  # round up


        dark_filename_t = 'dark_ccd{0:d}_{1:d}bit_{2:d}s_gain{3:d}_bin{4:d}_{5:d}c_{6:s}.fit'
        # 0  = ccd id
        # 1  = bits
        # 2  = exposure (seconds)
        # 3  = gain
        # 4  = binning
        # 5  = temperature
        # 6  = date
        # 7  = extension

        ### take darks

        ### NIGHT MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['NIGHT']['BINNING'])


        for exposure in dark_exposures:
            self._take_sigma_exposures(exposure, dark_filename_t, ccd_bits)

        ### NIGHT MOON MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        ### take darks
        for exposure in dark_exposures:
            self._take_sigma_exposures(exposure, dark_filename_t, ccd_bits)


        ### DAY DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        ### take darks
        # day will rarely exceed 1 second
        for exposure in dark_exposures:
            self._take_sigma_exposures(exposure, dark_filename_t, ccd_bits)



    def _take_sigma_exposures(self, exposure, dark_filename_t, ccd_bits):
        self.indiclient.getCcdTemperature(self.ccdDevice)

        exp_date = datetime.now()
        date_str = exp_date.strftime('%Y%m%d_%H%M%S')
        filename = dark_filename_t.format(
            self.camera_id,
            ccd_bits,
            int(exposure),
            self.gain_v.value,
            self.bin_v.value,
            int(self.sensortemp_v.value),
            date_str,
        )

        full_filename_p = self.darks_dir.joinpath(filename)


        tmp_fit_dir = tempfile.TemporaryDirectory()
        tmp_fit_dir_p = Path(tmp_fit_dir.name)

        logger.info('Temp folder: %s', tmp_fit_dir_p)

        image_bitpix = None
        for c in range(self._count):
            start = time.time()

            self.shoot(self.ccdDevice, float(exposure), sync=True)

            elapsed_s = time.time() - start

            logger.info('Exposure received in %0.4f s', elapsed_s)


            hdulist = self._wait_for_image()
            hdulist[0].header['BUNIT'] = 'ADU'  # hack for ccdproc

            image_bitpix = hdulist[0].header['BITPIX']

            f_tmp_fit = tempfile.NamedTemporaryFile(dir=tmp_fit_dir_p, suffix='.fit', delete=False)
            hdulist.writeto(f_tmp_fit)
            f_tmp_fit.flush()
            f_tmp_fit.close()

            logger.info('FIT: %s', f_tmp_fit.name)


        self.stack_darks(tmp_fit_dir_p, full_filename_p, exposure, image_bitpix)

        self._miscDb.addDarkFrame(
            full_filename_p,
            self.camera_id,
            image_bitpix,
            exposure,
            self.gain_v.value,
            self.bin_v.value,
            self.sensortemp_v.value,
        )


        tmp_fit_dir.cleanup()




    def stack_darks(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        logger.info('Stacking dark frames for exposure %0.1fs, gain %d, bin %d', exposure, self.gain_v.value, self.bin_v.value)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8

        dark_images = ccdproc.ImageFileCollection(tmp_fit_dir_p)

        cal_darks = dark_images.files_filtered(imagetyp='Dark Frame', exptime=exposure, include_path=True)

        combined_dark = ccdproc.combine(
            cal_darks,
            method='average',
            sigma_clip=True,
            sigma_clip_low_thresh=5,
            sigma_clip_high_thresh=5,
            sigma_clip_func=numpy.ma.median,
            signma_clip_dev_func=mad_std,
            dtype=numpy_type,
            mem_limit=350000000,
        )

        combined_dark.meta['combined'] = True

        combined_dark.write(filename_p)


    def flush(self):
        dark_frames_all = IndiAllSkyDbDarkFrameTable.query

        logger.warning('Found %d dark frames to flush', dark_frames_all.count())

        time.sleep(5.0)

        for dark_frame_entry in dark_frames_all:
            filename = Path(dark_frame_entry.filename)

            if filename.exists():
                logger.warning('Removing dark frame: %s', filename)
                filename.unlink()


        dark_frames_all.delete()
        db.session.commit()


