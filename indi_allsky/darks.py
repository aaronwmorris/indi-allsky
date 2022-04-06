import sys
import io
import time
import math
import tempfile
import json
from datetime import datetime
from pathlib import Path
import logging

import numpy
from astropy.io import fits

import ccdproc
from astropy.stats import mad_std

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
        self._temperature_delta = 5.0


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
        #logger.info('Changing image count to %d', int(new_count))
        self._count = int(new_count)


    @property
    def tdelta(self):
        return self._temperature_delta

    @tdelta.setter
    def tdelta(self, new_delta):
        self._temperature_delta = float(abs(new_delta))



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



    def average(self):
        self._initialize()

        self._run(IndiAllSkyDarksAverage)


    def tempaverage(self):
        self._initialize()

        current_temp = self.indiclient.getCcdTemperature(self.ccdDevice)
        next_temp_thold = current_temp - self._temperature_delta

        # get first set of images
        self._run(IndiAllSkyDarksAverage)

        while True:
            # This loop will run forever, it is up to the user to cancel
            current_temp = self.indiclient.getCcdTemperature(self.ccdDevice)

            logger.info('Next temperature threshold: %0.1f', next_temp_thold)

            if current_temp > next_temp_thold:
                time.sleep(20.0)
                continue

            logger.warning('Acheived next temperature threshold')
            next_temp_thold = next_temp_thold - self._temperature_delta

            self._run(IndiAllSkyDarksAverage)



    def sigmaclip(self):
        self._initialize()

        self._run(IndiAllSkyDarksSigmaClip)


    def tempsigmaclip(self):
        self._initialize()

        current_temp = self.indiclient.getCcdTemperature(self.ccdDevice)
        next_temp_thold = current_temp - self._temperature_delta

        # get first set of images
        self._run(IndiAllSkyDarksSigmaClip)

        while True:
            # This loop will run forever, it is up to the user to cancel
            current_temp = self.indiclient.getCcdTemperature(self.ccdDevice)

            logger.info('Next temperature threshold: %0.1f', next_temp_thold)

            if current_temp > next_temp_thold:
                time.sleep(20.0)
                continue

            logger.warning('Acheived next temperature threshold')
            next_temp_thold = next_temp_thold - self._temperature_delta

            self._run(IndiAllSkyDarksSigmaClip)



    def _run(self, stacking_class):

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
            self._take_exposures(exposure, dark_filename_t, ccd_bits, stacking_class)

        ### NIGHT MOON MODE DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['MOONMODE']['BINNING'])


        ### take darks
        for exposure in dark_exposures:
            self._take_exposures(exposure, dark_filename_t, ccd_bits, stacking_class)


        ### DAY DARKS ###
        self.indiclient.setCcdGain(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['GAIN'])
        self.indiclient.setCcdBinning(self.ccdDevice, self.config['CCD_CONFIG']['DAY']['BINNING'])


        ### take darks
        # day will rarely exceed 1 second
        for exposure in dark_exposures:
            self._take_exposures(exposure, dark_filename_t, ccd_bits, stacking_class)



    def _take_exposures(self, exposure, dark_filename_t, ccd_bits, stacking_class):
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


        s = stacking_class(self.gain_v, self.bin_v)
        s.stack(tmp_fit_dir_p, full_filename_p, exposure, image_bitpix)


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



    def flush(self):
        dark_frames_all = IndiAllSkyDbDarkFrameTable.query

        logger.warning('Found %d dark frames to flush', dark_frames_all.count())

        time.sleep(10.0)

        for dark_frame_entry in dark_frames_all:
            filename = Path(dark_frame_entry.filename)

            if filename.exists():
                logger.warning('Removing dark frame: %s', filename)
                filename.unlink()


        dark_frames_all.delete()
        db.session.commit()



class IndiAllSkyDarksProcessor(object):
    def __init__(self, gain_v, bin_v):
        self.gain_v = gain_v
        self.bin_v = bin_v

    def stack(self):
        raise Exception('Must be redefined in sub-class')


class IndiAllSkyDarksAverage(IndiAllSkyDarksProcessor):
    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
        logger.info('Stacking dark frames for exposure %0.1fs, gain %d, bin %d', exposure, self.gain_v.value, self.bin_v.value)

        if image_bitpix == 16:
            numpy_type = numpy.uint16
        elif image_bitpix == 8:
            numpy_type = numpy.uint8
        else:
            raise Exception('Unknown bits per pixel')

        image_data = list()
        hdulist = None
        for item in Path(tmp_fit_dir_p).iterdir():
            #logger.info('Found item: %s', item)
            if item.is_file() and item.suffix in ('.fit',):
                #logger.info('Found fit: %s', item)
                hdulist = fits.open(item)
                image_data.append(hdulist[0].data)

        avg_image = numpy.average(image_data, axis=0)

        data = numpy.floor(avg_image).astype(numpy_type)

        hdulist[0].data = data

        # reuse the last fits file for the stacked data
        hdulist.writeto(filename_p)



class IndiAllSkyDarksSigmaClip(IndiAllSkyDarksProcessor):
    def stack(self, tmp_fit_dir_p, filename_p, exposure, image_bitpix):
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


