#!/usr/bin/env python3


import time
import subprocess
import tempfile
from pathlib import Path
import logging


logging.basicConfig(level=logging.INFO)
logger = logging



class LibCameraProcess(object):
    def __init__(self):
        self.exposure = 5
        self._ccd_gain = 1

        self.exposureStartTime = None
        self.libcamera_process = None
        self.current_exposure_file_p = None


    def main(self):
        image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.dng', delete=False)
        image_tmp_p = Path(image_tmp_f.name)
        image_tmp_f.close()

        self.current_exposure_file_p = image_tmp_p

        exposure_us = int(self.exposure * 1000000)

        cmd = [
            'libcamera-still',
            '--immediate',
            '--nopreview',
            '--raw',
            '--denoise', 'off',
            '--awbgains', '1,1',  # disable awb
            '--gain', '{0:d}'.format(self._ccd_gain),
            '--shutter', '{0:d}'.format(exposure_us),
            '--output', str(image_tmp_p),
        ]

        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.libcamera_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )



        while True:
            poll = self.libcamera_process.poll()
            logger.info('Poll result: %s', str(poll))

            if not isinstance(poll, type(None)):
                exposure_elapsed_s = time.time() - self.exposureStartTime
                logger.info('Exposure time: %0.2f', exposure_elapsed_s)
                break

            time.sleep(0.2)



        #while True:
        #    size = self.current_exposure_file_p.stat().st_size

        #    logger.info('File size: %d', size)

        #    if size != 0:
        #        break

        #    time.sleep(0.2)



        if self.libcamera_process.returncode != 0:
            # log errors
            stdout = self.libcamera_process.stdout
            for line in stdout.readlines():
                logger.error('libcamera-still error: %s', line)



        # delete image
        image_tmp_p.unlink()



if __name__ == "__main__":
    lcp = LibCameraProcess()
    lcp.main()
