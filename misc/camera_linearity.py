#!/usr/bin/env python3

import sys
from pathlib import Path
import argparse
import math
import time
from datetime import datetime
import signal
import ctypes
import logging
import traceback

from prettytable import PrettyTable
from pprint import pformat  # noqa: F401

import numpy
import cv2

import queue
from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Array

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import Float
from sqlalchemy import DateTime
from sqlalchemy.sql import func
from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound


sys.path.insert(0, str(Path(__file__).parent.absolute().parent))

#from indi_allsky import constants
from indi_allsky.config import IndiAllSkyConfig
from indi_allsky.utils import IndiAllSkyExposureUtils
from indi_allsky import camera as camera_module
from indi_allsky.processing import ImageProcessor
from indi_allsky.flask import create_app

from indi_allsky.flask.models import IndiAllSkyDbCameraTable

from indi_allsky.exceptions import IndiServerException
from indi_allsky.exceptions import CameraException
from indi_allsky.exceptions import TimeOutException
from indi_allsky.exceptions import BadImage


app = create_app()

logger = logging.getLogger('indi_allsky')
logger.setLevel(logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


### Staring exposure
### Exposures levels will increase by 50% until at least 1s
### None == camera minimum
EXPOSURE_START = None


class CameraLinearityTest(object):

    def __init__(self):
        with app.app_context():
            try:
                self._config_obj = IndiAllSkyConfig()
                #logger.info('Loaded config id: %d', self._config_obj.config_id)
            except NoResultFound:
                logger.error('No config file found, please import a config')
                sys.exit(1)

        self.config = self._config_obj.config

        self.sensors_temp_av = Array('f', [0.0 for x in range(60)])
        self.sensors_user_av = Array('f', [0.0 for x in range(110)])


        self.position_av = Array('f', [
            float(self.config['LOCATION_LATITUDE']),
            float(self.config['LOCATION_LONGITUDE']),
            float(self.config.get('LOCATION_ELEVATION', 300)),
            0.0,  # Ra
            0.0,  # Dec
        ])


        ### all values in microseconds (0.000001 second)
        self.exposure_av = Array(ctypes.c_int32, [
            -1,  # current exposure - these must be -1 to indicate unset
            -1,  # next exposure
            -1,  # exposure delta
            -1,  # night minimum
            -1,  # day minimum
            -1,  # maximum
            -1,  # sqm
        ])


        ### unit 1/1000 gain (0.001 gain)
        self.gain_av = Array(ctypes.c_int32, [
            -1,  # current gain
            -1,  # next gain
            -1,  # gain delta
            -1,  # day minimum
            -1,  # day maximum
            -1,  # night minimum
            -1,  # night maximum
            -1,  # moon mode minimum
            -1,  # moon mode maximum
            -1,  # sqm
        ])


        self.binning_av = Array('i', [
            -1,  # current bin
            -1,  # next bin
            -1,  # day bin
            -1,  # night bin
            -1,  # moonmode bin
            -1,  # sqm
        ])


        self.night_av = Array('i', [
            -1,  # night, bogus initial value
            -1,  # moonmode, bogus initial value
        ])


        self.astro_av = Array('f', [
            0.0,  # sun alt
            0.0,  # moon alt
            0.0,  # moon percent
        ])


        self.image_processor = ImageProcessor(
            self.config,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.sensors_temp_av,
            self.sensors_user_av,
            self.night_av,
            self.astro_av,
        )


        self.capture_q = Queue()
        self.capture_error_q = Queue()
        self.capture_worker = None
        self.capture_worker_idx = 0

        self.image_q = Queue()

        self.image_count = 0
        self._adu_mask_dict = {
            1 : None,
            2 : None,
            4 : None,
        }

        self._offset = None
        self._exposure_count = None
        self._calibrate = None

        self.session = self._getDbConn()

        self._shutdown = False

        signal.signal(signal.SIGINT, self.sigint_handler_main)


    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, new_offset):
        self._offset = int(new_offset)
        logger.warning('Using offset: %d', self.offset)


    @property
    def exposure_count(self):
        return self._exposure_count

    @exposure_count.setter
    def exposure_count(self, new_exposure_count):
        self._exposure_count  = int(new_exposure_count)


    @property
    def calibrate(self):
        return self._calibrate

    @calibrate.setter
    def calibrate(self, new_calibrate):
        self._calibrate = bool(new_calibrate)

        if self.calibrate:
            logger.warning('Image Calibration Enabled')
        else:
            logger.warning('Image Calibration Disabled')


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True


    def main(self):
        self._startCaptureWorker()

        while True:
            if self._shutdown:
                logger.warning('Shutting down')
                break


            i_dict = self.image_q.get()  # blocking


            if not i_dict.get('exposure'):
                break


            with app.app_context():
                self.processImage(i_dict)


        self._stopCaptureWorker()

        self.generateReport()


    def processImage(self, i_dict):
        filename_p = Path(i_dict['filename'])
        exposure = i_dict['exposure']
        gain = i_dict['gain']
        binning = i_dict['binning']
        exp_date = datetime.fromtimestamp(i_dict['exp_time'])
        exp_elapsed = i_dict['exp_elapsed']
        camera_id = i_dict['camera_id']
        detected_camera_name = i_dict.get('camera_name')
        libcamera_black_level = i_dict.get('libcamera_black_level', 0)


        logger.info('Camera ID: %d', camera_id)

        camera = IndiAllSkyDbCameraTable.query\
            .filter(IndiAllSkyDbCameraTable.id == camera_id)\
            .one()



        try:
            i_ref = self.image_processor.add(
                filename_p,
                exposure,
                gain,
                binning,
                exp_date,
                exp_elapsed,
                camera,
                detected_camera_name=detected_camera_name,
            )
        except BadImage as e:
            logger.error('Bad Image: %s', str(e))
            filename_p.unlink()
            #task.setFailed('Bad Image: {0:s}'.format(str(filename_p)))
            return


        filename_p.unlink()  # original file is no longer needed


        self.image_count += 1


        # use original value if not defined
        if i_ref.libcamera_black_level:
            libcamera_black_level = i_ref.libcamera_black_level  # noqa: F841


        if self.calibrate:
            self.image_processor.calibrate(libcamera_black_level=libcamera_black_level)

        self.image_processor.debayer()  # populates self.opencv_data

        image = i_ref.opencv_data

        if isinstance(self._adu_mask_dict[i_ref.binning], type(None)):
            # This only needs to be done once if a mask is not provided
            self._generateAduMask(image, i_ref.binning)


        if len(image.shape) == 2:
            # mono
            adu = cv2.mean(src=image, mask=self._adu_mask_dict[i_ref.binning])[0]
        else:
            data_mono = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            adu = cv2.mean(src=data_mono, mask=self._adu_mask_dict[i_ref.binning])[0]


        # subtract the manual offset
        adu -= self.offset


        logger.info('ADU: %0.1f', adu)
        adu_entry = LinearityTable(
            exposure=exposure,
            adu=adu,
        )
        self.session.add(adu_entry)
        self.session.commit()


    def generateReport(self):
        table_report = PrettyTable()
        table_report.field_names = [
            'Exposure',
            'Count',
            'ADU Average',
            #'Prev Exposure',
            'Exposure Diff',
            #'Prev ADU',
            'ADU Diff',
            'Exposure Diff %',
            'ADU Diff %',
        ]


        adu_avg = func.avg(LinearityTable.adu)

        q = self.session.query(
            LinearityTable.exposure,
            adu_avg.label('adu_avg_current'),
            func.count(LinearityTable.exposure).label('exposure_count'),
            func.lag(LinearityTable.exposure, 1).over(
                order_by=LinearityTable.createDate,
            ).label('exposure_previous'),
            (LinearityTable.exposure - func.lag(LinearityTable.exposure, 1).over(
                order_by=LinearityTable.createDate,
            )).label('exposure_diff'),
            func.lag(adu_avg, 1).over(
                order_by=LinearityTable.createDate,
            ).label('adu_avg_previous'),
            (100 * LinearityTable.exposure / func.lag(LinearityTable.exposure, 1).over(
                order_by=LinearityTable.createDate,
            ) - 100).label('exposure_percent_diff'),
            (adu_avg - func.lag(adu_avg, 1).over(
                order_by=LinearityTable.createDate,
            )).label('adu_avg_diff'),
            (100 * (adu_avg / func.lag(adu_avg, 1).over(
                order_by=LinearityTable.createDate,
            )) - 100).label('adu_percent_diff'),
        )\
            .group_by(LinearityTable.exposure)\
            .order_by(LinearityTable.exposure)


        for entry in q:
            if isinstance(entry.adu_avg_diff, type(None)):
                # skip first entry
                continue

            table_report.add_row([
                '{0:0.6f}'.format(entry.exposure),
                '{0:d}'.format(entry.exposure_count),
                '{0:0.4f}'.format(entry.adu_avg_current),
                #'{0:0.6f}'.format(entry.exposure_previous),
                '{0:+0.6f}'.format(entry.exposure_diff),
                #'{0:0.4f}'.format(entry.adu_avg_previous),
                '{0:+0.4f}'.format(entry.adu_avg_diff),
                '{0:+0.1f}'.format(entry.exposure_percent_diff),
                '{0:+0.1f}'.format(entry.adu_percent_diff),
            ])


        print(table_report)


    def _getDbConn(self):
        engine = create_engine('sqlite://', echo=False)  # In memory db
        #engine = create_engine('sqlite:///{0:s}'.format(str(Path(__file__).parent.joinpath('year.sqlite'))), echo=False)
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        return Session()


    def _startCaptureWorker(self):
        if self.capture_worker:
            if self.capture_worker.is_alive():
                return

            try:
                capture_error, capture_traceback = self.capture_error_q.get_nowait()
                for line in capture_traceback.split('\n'):
                    logger.error('Capture worker exception: %s', line)
            except queue.Empty:
                pass


        self.capture_worker_idx += 1

        logger.info('Starting Capture-%d worker', self.capture_worker_idx)
        self.capture_worker = CaptureWorker(
            self.capture_worker_idx,
            self.config,
            self.capture_error_q,
            self.capture_q,
            self.image_q,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
            self.astro_av,
            exposure_count=self.exposure_count,
        )

        self.capture_worker.start()


    def _stopCaptureWorker(self):
        if not self.capture_worker:
            return

        if not self.capture_worker.is_alive():
            return

        logger.info('Stopping Capture worker')

        self.capture_q.put({'stop' : True})
        self.capture_worker.join()


    def _generateAduMask(self, img, binning):
        logger.info('Generating mask based on ADU_ROI')

        image_height, image_width = img.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        logger.warning('Using central ROI for ADU calculations')
        adu_fov_div = self.config.get('ADU_FOV_DIV', 4)
        x1 = int((image_width / 2) - (image_width / adu_fov_div))
        y1 = int((image_height / 2) - (image_height / adu_fov_div))
        x2 = int((image_width / 2) + (image_width / adu_fov_div))
        y2 = int((image_height / 2) + (image_height / adu_fov_div))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=255,  # mono
            thickness=cv2.FILLED,
        )

        self._adu_mask_dict[binning] = mask


class CaptureWorker(Process):
    def __init__(
        self,
        idx,
        config,
        error_q,
        capture_q,
        image_q,
        position_av,
        exposure_av,
        gain_av,
        binning_av,
        night_av,
        astro_av,
        exposure_count=3
    ):

        super(CaptureWorker, self).__init__()

        self.name = 'Capture-{0:d}'.format(idx)

        self.config = config
        self.error_q = error_q
        self.capture_q = capture_q
        self.image_q = image_q

        self.position_av = position_av
        self.exposure_av = exposure_av
        self.gain_av = gain_av
        self.binning_av = binning_av

        self.night_av = night_av
        self.astro_av = astro_av

        self._expUtils = IndiAllSkyExposureUtils(self.config, self.exposure_av, self.gain_av, self.binning_av)

        self.indiclient = None
        self.camera = None

        self._exposure_count = None
        self.exposure_count = exposure_count

        self._shutdown = False


    @property
    def exposure_count(self):
        return self._exposure_count

    @exposure_count.setter
    def exposure_count(self, new_exposure_count):
        self._exposure_count  = int(new_exposure_count)
        logger.warning('Taking %d exposures per level', self.exposure_count)


    def sigint_handler_worker(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def run(self):
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGINT, self.sigint_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e


    def saferun(self):
        with app.app_context():
            self._initialize()


        min_exposure = self._expUtils.EXPOSURE_MIN_DAY
        gain = self._expUtils.GAIN_MIN_DAY
        binning = self._expUtils.BINNING_DAY


        if isinstance(EXPOSURE_START, type(None)):
            exposure = min_exposure
        else:
            exposure = EXPOSURE_START


        exposures_list = list()
        while exposure < 1:  # keep exposures under 1s
            for _ in range(self.exposure_count):
                exposures_list.append({
                    'exposure' : exposure,
                    'gain'     : gain,
                    'binning'  : binning
                })

            exposure *= 1.75


        #logger.info('Exposures: %s', pformat(exposures_list))


        frame_start_time = time.time()
        waiting_for_frame = False

        camera_ready_time = time.time()
        camera_ready = False
        exposure_state = 'unset'



        ### main loop starts
        while True:
            loop_start_time = time.time()

            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            try:
                c_dict = self.capture_q.get(False)

                if c_dict.get('stop'):
                    self._shutdown = True
                else:
                    logger.error('Unknown action: %s', str(c_dict))

            except queue.Empty:
                pass


            # Loop to run for 11 seconds (prime number)
            loop_end = time.time() + 11

            while True:
                time.sleep(0.05)

                now_time = time.time()
                if now_time >= loop_end:
                    break

                last_camera_ready = camera_ready


                camera_ready, exposure_state = self.indiclient.getCcdExposureStatus()


                if not camera_ready:
                    continue

                ###########################################
                # Camera is ready, not taking an exposure #
                ###########################################
                if not last_camera_ready:
                    camera_ready_time = now_time


                if waiting_for_frame:
                    frame_elapsed = now_time - frame_start_time
                    frame_delta = frame_elapsed - self._expUtils.EXPOSURE_CURRENT

                    waiting_for_frame = False

                    logger.info('Exposure received in %0.4fs (%+0.4fs)', frame_elapsed, frame_delta)



                ##########################################################################
                # Here we know the camera is not busy and we are not waiting for a frame #
                ##########################################################################

                # shutdown here to ensure camera is not taking images
                if self._shutdown:
                    logger.warning('Shutting down')

                    self.indiclient.disableCcdCooler()  # safety

                    self.indiclient.disconnectServer()

                    logger.warning('Goodbye')
                    return


                #######################
                # Start next exposure #
                #######################
                total_elapsed = now_time - frame_start_time
                logger.info('Total time since last exposure %0.4f s', total_elapsed)

                frame_start_time = now_time


                try:
                    e = exposures_list.pop(0)

                    self._expUtils.EXPOSURE_NEXT = e['exposure']
                    self._expUtils.GAIN_NEXT = e['gain']
                    self._expUtils.BINNING_NEXT = e['binning']

                except IndexError:
                    logger.warning('REACHED END OF LIST')

                    self.image_q.put({
                        'exposure' : None,
                    })

                    return


                self.shoot(
                    self._expUtils.EXPOSURE_NEXT,
                    self._expUtils.GAIN_NEXT,
                    self._expUtils.BINNING_NEXT,
                    sync=False,
                )


                loop_elapsed = time.time() - loop_start_time
                logger.debug('Loop completed in %0.4f s', loop_elapsed)



    def _initialize(self):
        camera_interface = getattr(camera_module, self.config.get('CAMERA_INTERFACE', 'indi'))


        # instantiate the client
        self.indiclient = camera_interface(
            self.config,
            self.image_q,
            self.position_av,
            self.exposure_av,
            self.gain_av,
            self.binning_av,
            self.night_av,
        )


        # set indi server localhost and port
        self.indiclient.setServer(self.config['INDI_SERVER'], self.config['INDI_PORT'])

        # connect to indi server
        logger.info("Connecting to indiserver")
        if not self.indiclient.connectServer():
            host = self.indiclient.getHost()
            port = self.indiclient.getPort()

            logger.error("No indiserver available at %s:%d", host, port)
            raise IndiServerException('indiserver not available')


        # give devices a chance to register
        time.sleep(5)

        try:
            self.indiclient.findCcd(camera_name=self.config.get('INDI_CAMERA_NAME'))
        except CameraException as e:
            logger.error('Camera error: !!! %s !!!', str(e).upper())
            time.sleep(60)
            raise


        logger.warning('Connecting to CCD device %s', self.indiclient.ccd_device.getDeviceName())
        self.indiclient.connectDevice(self.indiclient.ccd_device.getDeviceName())


        # use day config by default
        if self.config.get('INDI_CONFIG_DAY', {}):
            indi_config = self.config['INDI_CONFIG_DAY']
        else:
            indi_config = self.config['INDI_CONFIG_DEFAULTS']

        self.indiclient.configureCcdDevice(indi_config)


        # get CCD information
        ccd_info = self.indiclient.getCcdInfo()


        try:
            # Disable debugging
            self.indiclient.disableDebugCcd()
        except TimeOutException:
            logger.warning('Camera does not support debug')


        # set BLOB mode to BLOB_ALSO
        self.indiclient.updateCcdBlobMode()


        try:
            self.indiclient.setCcdFrameType('FRAME_LIGHT')  # default frame type is light
        except TimeOutException:
            # this is an optional step
            # occasionally the CCD_FRAME_TYPE property is not available during initialization
            logger.warning('Unable to set CCD_FRAME_TYPE to Light')


        # set exposure limits
        # prevent python/C float conversion errors
        ccd_min_exp = math.ceil(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['min']) * 1000000) / 1000000
        #ccd_max_exp = math.floor(float(ccd_info['CCD_EXPOSURE']['CCD_EXPOSURE_VALUE']['max']) * 1000000) / 1000000


        config_exposure_min_day = math.ceil(float(self.config.get('CCD_EXPOSURE_MIN_DAY', 0.0) * 1000000)) / 1000000


        if not config_exposure_min_day:
            self._expUtils.EXPOSURE_MIN_DAY = ccd_min_exp
        elif config_exposure_min_day < ccd_min_exp:
            logger.warning(
                'Minimum exposure (day) %0.6f too low, increasing to %0.6f',
                config_exposure_min_day,
                ccd_min_exp,
            )
            self._expUtils.EXPOSURE_MIN_DAY = ccd_min_exp
        else:
            self._expUtils.EXPOSURE_MIN_DAY = config_exposure_min_day

        logger.info('Minimum CCD exposure: %0.6f (day)', self._expUtils.EXPOSURE_MIN_DAY)


        ### Validate gain settings
        # prevent python/C float conversion errors
        ccd_min_gain = math.ceil(float(ccd_info['GAIN_INFO']['min']) * 1000) / 1000  # round up the thousands spot
        ccd_max_gain = math.floor(float(ccd_info['GAIN_INFO']['max']) * 1000) / 1000  # round down

        config_day_gain = math.ceil(float(self.config['CCD_CONFIG']['DAY']['GAIN']) * 1000) / 1000


        if config_day_gain < ccd_min_gain:
            logger.error('CCD day gain below minimum, changing to %0.3f', ccd_min_gain)
            gain_day = ccd_min_gain
            time.sleep(3)
        elif config_day_gain > ccd_max_gain:
            logger.error('CCD day gain above maximum, changing to %0.3f', ccd_max_gain)
            gain_day = ccd_max_gain
            time.sleep(3)
        else:
            gain_day = config_day_gain


        self._expUtils.GAIN_MIN_DAY = gain_day


        # Validate binning settings
        ccd_min_binning = int(ccd_info['BINNING_INFO']['min'])
        ccd_max_binning = int(ccd_info['BINNING_INFO']['max'])


        if self.config['CCD_CONFIG']['DAY']['BINNING'] < ccd_min_binning:
            logger.error('CCD day binning below minimum, changing to %d', ccd_min_binning)
            binning_day = ccd_min_binning
            time.sleep(3)
        elif self.config['CCD_CONFIG']['DAY']['BINNING'] > ccd_max_binning:
            logger.error('CCD day binning above maximum, changing to %d', ccd_max_binning)
            binning_day = ccd_max_binning
            time.sleep(3)
        else:
            binning_day = int(self.config['CCD_CONFIG']['DAY']['BINNING'])


        self._expUtils.BINNING_DAY = binning_day


        metadata = {
            'name'        : self.indiclient.getIndiAllskyCameraName(),  # allow camera to have derived name
            'serialNumber': ccd_info.get('SERIALNUMBER_INFO', {}).get('text'),

            'minExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('min')),
            'maxExposure' : float(ccd_info.get('CCD_EXPOSURE', {}).get('CCD_EXPOSURE_VALUE', {}).get('max')),
            'minGain'     : float(ccd_info.get('GAIN_INFO', {}).get('min')),
            'maxGain'     : float(ccd_info.get('GAIN_INFO', {}).get('max')),
            'minBinning'  : int(ccd_info.get('BINNING_INFO', {}).get('min')),
            'maxBinning'  : int(ccd_info.get('BINNING_INFO', {}).get('max')),
        }


        if metadata['serialNumber']:
            # match serial number first
            try:
                # not catching MultipleResultsFound
                self.camera = IndiAllSkyDbCameraTable.query\
                    .filter(IndiAllSkyDbCameraTable.serialNumber == metadata['serialNumber'])\
                    .one()


                logger.info('Matched camera serial number: %s', metadata['serialNumber'])
            except NoResultFound:
                pass


        if isinstance(self.camera, type(None)):
            # if no serial matched, match camera name
            try:
                # not catching MultipleResultsFound
                self.camera = IndiAllSkyDbCameraTable.query\
                    .filter(
                        or_(
                            IndiAllSkyDbCameraTable.name == metadata['name'],
                            IndiAllSkyDbCameraTable.name_alt1 == metadata['name'],
                            IndiAllSkyDbCameraTable.name_alt2 == metadata['name'],
                        )
                    )\
                    .one()


                logger.info('Matched camera name: %s', metadata['name'])

            except NoResultFound:
                raise


        self.indiclient.camera_id = self.camera.id


    def shoot(self, exposure, gain, binning, sync=True, timeout=None):
        # sqm used for an image taking at a specific exposure/gain for a controlled SQM measurement
        logger.info('Taking %0.6fs exposure (gain %0.3f / bin %d)', exposure, gain, binning)

        self.indiclient.setCcdExposure(exposure, gain, binning, sync=sync, timeout=timeout, sqm_exposure=False)


class Base(DeclarativeBase):
    pass


class LinearityTable(Base):
    __tablename__ = 'linearity'

    id          = Column(Integer, primary_key=True)
    createDate  = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    exposure    = Column(Float, nullable=False, index=True)
    adu         = Column(Float, nullable=False)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()

    argparser.add_argument(
        '--Count',
        '-C',
        help='exposure count [default: 3]',
        type=int,
        default=3,
    )
    argparser.add_argument(
        '--offset',
        '-o',
        help='camera offset [default: 0]',
        type=int,
        default=0,
    )

    calibrate_group = argparser.add_mutually_exclusive_group(required=False)
    calibrate_group.add_argument(
        '--no-calibrate',
        help='disable image calibration (default)',
        dest='calibrate',
        action='store_false',
    )
    calibrate_group.add_argument(
        '--calibrate',
        help='enable image calibration',
        dest='calibrate',
        action='store_true',
    )
    calibrate_group.set_defaults(calibrate=False)


    args = argparser.parse_args()


    clt = CameraLinearityTest()
    clt.exposure_count = args.Count
    clt.offset = args.offset
    clt.calibrate = args.calibrate
    clt.main()
