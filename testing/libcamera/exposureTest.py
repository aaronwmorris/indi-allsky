#!/usr/bin/env python3

import sys
from pathlib import Path
import time
import shutil
import subprocess
import tempfile
import signal
import logging


CAMERA_ID = 0

CCD_EXPOSURES = [15 for x in range(6000)]
#CCD_EXPOSURES = [
#    15.0,
#    14.0,
#    14.0,
#    10.0,
#     9.0,
#     7.0,
#     6.0,
#     5.0,
#     3.0,
#     1.0,
#]


### rpicam
CCD_GAIN = [1]
#CCD_GAIN = [
#    10,
#    10,
#    10,
#    25,
#    25,
#    25,
#    50,
#    50,
#    50,
#    100,
#    100,
#    100
#]  # loop through these forever



logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class LibCameraExposureTest(object):
    def __init__(self):
        self.active_exposure = None
        self.exposureStartTime = None
        self.libcamera_process = None
        self.current_exposure_file_p = None
        self.gain = 0
        self.current_gain = 0
        self._gain_index = 0


        # pick correct executable
        if shutil.which('rpicam-still'):
            self.rpicam_still = 'rpicam-still'
        else:
            self.rpicam_still = 'libcamera-still'


        self._shutdown = False

        signal.signal(signal.SIGINT, self.sigint_handler_main)


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        # set flag for program to stop processes
        self._shutdown = True


    def run(self):
        next_frame_time = time.time()  # start immediately
        frame_start_time = time.time()
        waiting_for_frame = False

        camera_ready_time = time.time()
        camera_ready = False
        last_camera_ready = False
        exposure_state = 'unset'

        exposure = 0  # populated later
        last_exposure = 0


        ### main loop starts
        while True:
            loop_start_time = time.time()

            logger.info('Camera last ready: %0.1fs', loop_start_time - camera_ready_time)
            logger.info('Exposure state: %s', exposure_state)


            # Loop to run for 7 seconds (prime number)
            loop_end = time.time() + 7


            while True:
                time.sleep(0.05)

                now = time.time()
                if now >= loop_end:
                    break

                last_camera_ready = camera_ready
                camera_ready, exposure_state = self.getCcdExposureStatus()

                if camera_ready and not last_camera_ready:
                    camera_ready_time = now


                if camera_ready and waiting_for_frame:
                    frame_elapsed = now - frame_start_time

                    waiting_for_frame = False

                    logger.warning('Exposure received in ######## %0.4f s (%0.4f) ########', frame_elapsed, frame_elapsed - last_exposure)

                    if self.current_exposure_file_p.exists():
                        self.current_exposure_file_p.unlink()  # delete last exposure


                    if self._shutdown:
                        sys.exit(0)


                if camera_ready and now >= next_frame_time:
                    total_elapsed = now - frame_start_time

                    frame_start_time = now

                    last_exposure = exposure

                    try:
                        exposure = CCD_EXPOSURES.pop(0)
                    except IndexError:
                        logger.info('End of exposures')
                        sys.exit(0)


                    new_gain = self.getNextGain()
                    if new_gain != self.current_gain:
                        self.gain = new_gain


                    self.shoot(exposure)
                    waiting_for_frame = True

                    next_frame_time = frame_start_time + exposure

                    logger.info('Total time since last exposure %0.4f s', total_elapsed)


    def shoot(self, exposure):
        image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.dng', delete=False)
        image_tmp_p = Path(image_tmp_f.name)
        image_tmp_f.close()

        self.current_exposure_file_p = image_tmp_p

        exposure_us = int(exposure * 1000000)

        cmd = [
            self.rpicam_still,
            '--immediate',
            '--nopreview',
            '--camera', '{0:d}'.format(CAMERA_ID),
            '--raw',
            '--denoise', 'off',
            '--awbgains', '1,1',  # disable awb
            '--gain', '{0:d}'.format(self.gain),
            '--shutter', '{0:d}'.format(exposure_us),
            '--output', str(image_tmp_p),
        ]

        ### Testing
        #cmd = ['sleep', '15']

        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.libcamera_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if self._libCameraPidRunning():
            return False, 'BUSY'


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False


            if self.libcamera_process.returncode != 0:
                # log errors
                stdout = self.libcamera_process.stdout
                for line in stdout.readlines():
                    logger.error('rpicam-still error: %s', line)

                # not returning, just log the error


        return True, 'READY'


    def getNextGain(self):
        if type(CCD_GAIN) is int:
            return CCD_GAIN
        elif type(CCD_GAIN) in (list, tuple):

            try:
                gain = CCD_GAIN[self._gain_index]
            except IndexError:
                self._gain_index = 0
                gain = CCD_GAIN[self._gain_index]

            self._gain_index += 1

            return gain

        else:
            raise Exception('Unknown gain variable type')


    def _libCameraPidRunning(self):
        if not self.libcamera_process:
            return False

        # poll returns None when process is active, rc (normally 0) when finished
        poll = self.libcamera_process.poll()
        if isinstance(poll, type(None)):
            return True

        return False


if __name__ == "__main__":
    LibCameraExposureTest().run()
