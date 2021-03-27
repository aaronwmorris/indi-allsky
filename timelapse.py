#!/usr/bin/env python

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime
from datetime import timedelta
import copy
import functools
import math
import argparse
import subprocess

import ephem

from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import current_process
from multiprocessing import log_to_stderr

import PyIndi
from astropy.io import fits
import cv2
import numpy

#CCD_NAME         = "CCD Simulator"
#CCD_NAME         = "ZWO CCD ASI290MM"
CCD_NAME         = "SVBONY SV305 0"

EXPOSURE_PERIOD  = 15.10000   # time between beginning of each frame

CCD_GAIN_NIGHT   = 250
CCD_GAIN_DAY     = 10   # minimum gain is 10 for SV305

CCD_PROPERTIES = {
    'CCD_BINNING' : [1],
    'CCD_GAIN'    : [CCD_GAIN_NIGHT],
    'CCD_WBR'     : [120],
    'CCD_WBG'     : [75],
    'CCD_WBB'     : [140],
    'CCD_GAMMA'   : [100],
}

CCD_SWITCHES = {
    'FRAME_FORMAT' : [
        PyIndi.ISS_OFF,  # RAW12
        PyIndi.ISS_ON,   # RAW8
    ]
}


CCD_EXPOSURE_MAX    = 15.000000
CCD_EXPOSURE_MIN    =  0.000029
#CCD_EXPOSURE_DEF    =  1.000000
CCD_EXPOSURE_DEF    =  0.000100

TARGET_MEAN         = 45.0
TARGET_MEAN_MAX     = TARGET_MEAN + (TARGET_MEAN * 0.1)
TARGET_MEAN_MIN     = TARGET_MEAN - (TARGET_MEAN * 0.1)

LOCATION_LATITUDE   = '33'
LOCATION_LONGITUDE  = '-84'
NIGHT_SUN_ALT_DEG   = 15

FONT_FACE       = cv2.FONT_HERSHEY_SIMPLEX
FONT_HEIGHT     = 30
FONT_X          = 15
FONT_Y          = 30
FONT_COLOR      = (200, 200, 200)
FONT_AA         = cv2.LINE_AA
FONT_SCALE      = 1 * 0.80
FONT_THICKNESS  = 1


logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

logger = log_to_stderr()
logger.setLevel(logging.INFO)


class IndiClient(PyIndi.BaseClient):
 
    def __init__(self, img_q):
        super(IndiClient, self).__init__()

        self.img_q = img_q

        self.device = None
        self.logger = logging.getLogger('PyQtIndi.IndiClient')
        self.logger.info('creating an instance of PyQtIndi.IndiClient')


    def newDevice(self, d):
        self.logger.info("new device %s", d.getDeviceName())
        if d.getDeviceName() == CCD_NAME:
            self.logger.info("Set new device %s!", CCD_NAME)
            # save reference to the device in member variable
            self.device = d


    def newProperty(self, p):
        pName = p.getName()
        pDeviceName = p.getDeviceName()

        self.logger.info("new property %s for device %s", pName, pDeviceName)
        if self.device is not None and pName == "CONNECTION" and pDeviceName == self.device.getDeviceName():
            self.logger.info("Got property CONNECTION for %s!", CCD_NAME)
            # connect to device
            self.logger.info('Connect to device')
            self.connectDevice(self.device.getDeviceName())

            # set BLOB mode to BLOB_ALSO
            self.logger.info('Set BLOB mode')
            self.setBLOBMode(1, self.device.getDeviceName(), None)



    def removeProperty(self, p):
        self.logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        self.logger.info("new BLOB %s", bp.name)
        ### get image data
        imgdata = bp.getblobdata()

        ### process data in worker
        self.img_q.put(imgdata)


    def newSwitch(self, svp):
        self.logger.info ("new Switch %s for device %s", svp.name, svp.device)


    def newNumber(self, nvp):
        #self.logger.info("new Number %s for device %s", nvp.name, nvp.device)
        pass


    def newText(self, tvp):
        self.logger.info("new Text %s for device %s", tvp.name, tvp.device)


    def newLight(self, lvp):
        self.logger.info("new Light "+ lvp.name + " for device "+ lvp.device)


    def newMessage(self, d, m):
        #self.logger.info("new Message %s", d.messageQueue(m))
        pass


    def serverConnected(self):
        print("Server connected ({0}:{1})".format(self.getHost(), self.getPort()))


    def serverDisconnected(self, code):
        self.logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())


    def takeExposure(self, exposure):
        self.logger.info("Taking %0.6f s exposure", exposure)
        #get current exposure time
        exp = self.device.getNumber("CCD_EXPOSURE")
        # set exposure time to 5 seconds
        exp[0].value = exposure
        # send new exposure time to server/device
        self.sendNewNumber(exp)




class ImageProcessorWorker(Process):
    def __init__(self, img_q, exposure_v, gain_v, sensortemp_v, night_v, writefits=False):
        super(ImageProcessorWorker, self).__init__()

        self.img_q = img_q
        self.exposure_v = exposure_v
        self.gain_v = gain_v
        self.sensortemp_v = sensortemp_v
        self.night_v = night_v

        self.writefits = writefits

        self.stable_mean = False
        self.scale_factor = 1.0
        self.hist_mean = []

        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        #self.dark = fits.open('dark_7s_gain250.fit')
        self.dark = None

        self.name = current_process().name


    def run(self):
        while True:
            imgdata = self.img_q.get()

            if not imgdata:
                return


            import io

            ### OpenCV ###
            blobfile = io.BytesIO(imgdata)
            hdulist = fits.open(blobfile)
            scidata_uncalibrated = hdulist[0].data

            if self.writefits:
                self.write_fit(hdulist)

            scidata_calibrated = self.calibrate(scidata_uncalibrated)
            scidata_color = self.colorize(scidata_calibrated)

            self.calculate_histogram(scidata_color)

            #scidata_denoise = cv2.fastNlMeansDenoisingColored(
            #    scidata_color,
            #    None,
            #    h=3,
            #    hColor=3,
            #    templateWindowSize=7,
            #    searchWindowSize=21,
            #)

            self.image_text(scidata_color)
            self.write_jpg(scidata_color)


    def write_fit(self, hdulist):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        hdulist.writeto("{0}.fit".format(now_str))

        logger.info('Finished writing fit file')


    def write_jpg(self, scidata):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        folder = self.getImageFolder()

        cv2.imwrite("{0:s}/{1:s}.jpg".format(folder, now_str), scidata, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #cv2.imwrite("{0}.png".format(now_str), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite("{0}.tif".format(now_str), scidata)

        logger.info('Finished writing files')


    def getImageFolder(self):
        now = datetime.now()

        if now.hour < 12:
            day_ref = now - timedelta(hours=12)
        else:
            day_ref = now

        folder = '{0:s}/images/{1:s}'.format(self.base_dir, day_ref.strftime('%Y%m%d'))

        if not os.path.exists(folder):
            os.mkdir(folder)

        return folder


    def calibrate(self, scidata_uncalibrated):

        if not self.dark:
            return scidata_uncalibrated

        scidata = cv2.subtract(scidata_uncalibrated, self.dark[0].data)
        return scidata



    def colorize(self, scidata):
        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BayerGR2RGB)
        scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_GR2RGB)
        ###

        #scidata_rgb = self._convert_GRBG_to_RGB_8bit(scidata)

        #scidata_wb = self.white_balance2(scidata_rgb)
        #scidata_wb = self.white_balance3(scidata_rgb)
        scidata_wb = scidata_rgb


        #if self.roi is not None:
        #    scidata = scidata[self.roi[1]:self.roi[1]+self.roi[3], self.roi[0]:self.roi[0]+self.roi[2]]
        #hdulist[0].data = scidata

        return scidata_wb


    def image_text(self, data_bytes):
        #cv2.rectangle(
        #    img=data_bytes,
        #    pt1=(0, 0),
        #    pt2=(350, 125),
        #    color=(0, 0, 0),
        #    thickness=cv2.FILLED,
        #)

        cv2.putText(
            img=data_bytes,
            text=datetime.now().strftime('%Y%m%d %H:%M:%S'),
            org=(FONT_X, FONT_Y),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )

        cv2.putText(
            img=data_bytes,
            text='Exposure {0:0.6f}'.format(self.exposure_v.value),
            org=(FONT_X, FONT_Y + (FONT_HEIGHT * 1)),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )

        cv2.putText(
            img=data_bytes,
            text='Gain {0:d}'.format(self.gain_v.value),
            org=(FONT_X, FONT_Y + (FONT_HEIGHT * 2)),
            fontFace=FONT_FACE,
            color=FONT_COLOR,
            lineType=FONT_AA,
            fontScale=FONT_SCALE,
            thickness=FONT_THICKNESS,
        )


    def calculate_histogram(self, data_bytes):
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

        logger.info('R mean: %0.2f', r_avg)
        logger.info('G mean: %0.2f', g_avg)
        logger.info('B mean: %0.2f', b_avg)

         # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3

        logger.info('RGB average: %0.2f', k)


        if not self.stable_mean:
            self.recalculate_exposure(k)
            return


        self.hist_mean.insert(0, k)
        self.hist_mean = self.hist_mean[:10]  # only need last 10 values

        k_moving_average = functools.reduce(lambda a, b: a + b, self.hist_mean) / len(self.hist_mean)
        logger.info('Moving average: %0.2f', k_moving_average)

        if k_moving_average > TARGET_MEAN_MAX:
            logger.warning('Moving average exceeded target by 10%, recalculating next exposure')
            self.stable_mean = False
        elif k_moving_average < TARGET_MEAN_MIN:
            logger.warning('Moving average exceeded target by 10%, recalculating next exposure')
            self.stable_mean = False


    def recalculate_exposure(self, k):

        # Until we reach a good starting point, do not calculate a moving average
        if k <= TARGET_MEAN_MAX and k >= TARGET_MEAN_MIN:
            logger.warning('Found stable mean for exposure')
            self.stable_mean = True
            [self.hist_mean.insert(0, k) for x in range(10)]  # populate 10 entries
            return


        current_exposure = self.exposure_v.value

        # Scale the exposure up and down based on targets
        if k > TARGET_MEAN_MAX:
            new_exposure = current_exposure / (( k / float(TARGET_MEAN) ) * self.scale_factor)
        elif k < TARGET_MEAN_MIN:
            new_exposure = current_exposure * (( float(TARGET_MEAN) / k ) * self.scale_factor)
        else:
            new_exposure = current_exposure



        # Do not exceed the limits
        if new_exposure < CCD_EXPOSURE_MIN:
            new_exposure = CCD_EXPOSURE_MIN
        elif new_exposure > CCD_EXPOSURE_MAX:
            new_exposure = CCD_EXPOSURE_MAX


        with self.exposure_v.get_lock():
            logger.warning('New calculated exposure: %0.6f', new_exposure)
            self.exposure_v.value = new_exposure


    def white_balance3(self, data_bytes):
        ### ohhhh, contrasty
        lab = cv2.cvtColor(data_bytes, cv2.COLOR_RGB2LAB)

        l, a, b = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        new_lab = cv2.merge((cl, a, b))

        new_data = cv2.cvtColor(new_lab, cv2.COLOR_LAB2RGB)
        return new_data


    def white_balance2(self, data_bytes):
        ### This seems to work
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

         # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3
        kr = k / r_avg
        kg = k / g_avg
        kb = k / b_avg

        r = cv2.addWeighted(src1=r, alpha=kr, src2=0, beta=0, gamma=0)
        g = cv2.addWeighted(src1=g, alpha=kg, src2=0, beta=0, gamma=0)
        b = cv2.addWeighted(src1=b, alpha=kb, src2=0, beta=0, gamma=0)

        balance_img = cv2.merge([b, g, r])
        return balance_img


    def _convert_GRBG_to_RGB_8bit(self, data_bytes):
        data_bytes = numpy.frombuffer(data_bytes, dtype=numpy.uint8)
        even = data_bytes[0::2]
        odd = data_bytes[1::2]
        # Convert bayer16 to bayer8
        bayer8_image = (even >> 4) | (odd << 4)
        bayer8_image = bayer8_image.reshape((1080, 1920))
        # Use OpenCV to convert Bayer GRBG to RGB
        return cv2.cvtColor(bayer8_image, cv2.COLOR_BayerGR2RGB)



class IndiTimelapse(object):

    def __init__(self):
        self.img_q = Queue()
        self.indiclient = None
        self.device = None
        self.exposure_v = Value('f', copy.copy(CCD_EXPOSURE_DEF))
        self.gain_v = Value('i', copy.copy(CCD_GAIN_NIGHT))
        self.sensortemp_v = Value('f', 0)
        self.night_v = Value('i', 1)

        self.base_dir = os.path.dirname(os.path.abspath(__file__))


    def _initialize(self, writefits=False):
        logger.info('Starting ImageProcessorWorker process')
        self.img_process = ImageProcessorWorker(self.img_q, self.exposure_v, self.gain_v, self.sensortemp_v, self.night_v, writefits=writefits)
        self.img_process.start()

        # instantiate the client
        self.indiclient = IndiClient(self.img_q)

        # set roi
        #indiclient.roi = (270, 200, 700, 700) # region of interest for my allsky cam

        # set indi server localhost and port 7624
        self.indiclient.setServer("localhost", 7624)

        # connect to indi server
        print("Connecting to indiserver")
        if (not(self.indiclient.connectServer())):
             print("No indiserver running on {0}:{1} - Try to run".format(self.indiclient.getHost(), self.indiclient.getPort()))
             print("  indiserver indi_simulator_telescope indi_simulator_ccd")
             sys.exit(1)


        while not self.device:
            self.device = self.indiclient.getDevice(CCD_NAME)
            time.sleep(0.5)

        logger.info('Connected to device')

        ### Perform device config
        self.configureCcd()


    def configureCcd(self):
        ### Configure CCD Properties
        for key in CCD_PROPERTIES.keys():

            # loop until the property is populated
            indiprop = None
            while not indiprop:
                indiprop = self.device.getNumber(key)
                time.sleep(0.5)

            logger.info('Setting property %s', key)
            for i, value in enumerate(CCD_PROPERTIES[key]):
                logger.info(' %d: %s', i, str(value))
                indiprop[i].value = value
            self.indiclient.sendNewNumber(indiprop)



        ### Configure CCD Switches
        for key in CCD_SWITCHES:

            # loop until the property is populated
            indiswitch = None
            while not indiswitch:
                indiswitch = self.device.getSwitch(key)
                time.sleep(0.5)


            logger.info('Setting switch %s', key)
            for i, value in enumerate(CCD_SWITCHES[key]):
                logger.info(' %d: %s', i, str(value))
                indiswitch[i].s = value
            self.indiclient.sendNewSwitch(indiswitch)


        # Sleep after configuration
        time.sleep(1.0)


    def run(self):

        self._initialize()

        ### main loop starts
        while True:
            temp = self.device.getNumber("CCD_TEMPERATURE")
            if temp:
                with self.sensortemp_v.get_lock():
                    logger.info("Sensor temperature: %d", temp[0].value)
                    self.sensortemp_v.value = temp[0].value


            is_night = self.is_night()
            #logger.info('self.night_v.value: %r', self.night_v.value)
            #logger.info('is night: %r', is_night)

            ### Change gain when we change between day and night
            if self.night_v.value != int(is_night):
                logger.warning('Change between night and day')
                with self.night_v.get_lock():
                    self.night_v.value = int(is_night)

                with self.gain_v.get_lock():
                    if is_night:
                        self.gain_v.value = CCD_GAIN_NIGHT
                    else:
                        self.gain_v.value = CCD_GAIN_DAY


                prop_gain = None
                while not prop_gain:
                    prop_gain = self.device.getNumber('CCD_GAIN')
                    time.sleep(0.5)

                logger.info('Setting camera gain to %d', self.gain_v.value)
                prop_gain[0].value = self.gain_v.value
                self.indiclient.sendNewNumber(prop_gain)

                # Sleep after reconfiguration
                time.sleep(1.0)


            self.indiclient.takeExposure(self.exposure_v.value)
            time.sleep(EXPOSURE_PERIOD)


    def is_night(self):
        obs = ephem.Observer()
        obs.lon = LOCATION_LONGITUDE
        obs.lat = LOCATION_LATITUDE
        obs.date = datetime.utcnow()  # ephem expects UTC dates

        sun = ephem.Sun()
        sun.compute(obs)

        logger.info('Sun altitude: %s', sun.alt)
        return sun.alt < math.sin(NIGHT_SUN_ALT_DEG)



    def darks(self):

        self._initialize(writefits=True)

        prop_gain = None
        while not prop_gain:
            prop_gain = self.device.getNumber('CCD_GAIN')
            time.sleep(0.5)

        logger.info('Setting camera gain to %d', CCD_GAIN_NIGHT)
        prop_gain[0].value = CCD_GAIN_NIGHT
        self.indiclient.sendNewNumber(prop_gain)


        ### take 3 darks
        for x in range(3):
            self.indiclient.takeExposure(7.0)
            time.sleep(8)


        ### stop worker
        self.img_q.put(None)
        self.img_process.join()


    def avconv(self, timespec):
        imgfolder = '{0:s}/images/{1:s}'.format(self.base_dir, timespec)

        if not os.path.exists(imgfolder):
            logger.error('Image folder does not exist: %s', imgfolder)
            sys.exit(1)


        seqfolder = '{0:s}/sequence'.format(imgfolder)

        if not os.path.exists(seqfolder):
            logger.info('Creating sequence folder %s', seqfolder)
            os.mkdir(seqfolder)


        # delete all existing symlinks in seqfolder
        rmlinks = list(filter(os.path.islink, Path(seqfolder).iterdir()))
        if rmlinks:
            logger.warning('Removing existing symlinks in %s', seqfolder)
            for f in rmlinks:
                os.unlink(f)


        logger.info('Creating symlinked files for timelapse')
        timelapse_files = sorted(Path(imgfolder).glob('*.jpg'), key=os.path.getmtime)
        for i, f in enumerate(timelapse_files):
            symlink_name = '{0:s}/{1:04d}.jpg'.format(seqfolder, i)
            os.symlink(f, symlink_name)

        #cmd = 'ffmpeg -y -f image2 -r {0:d} -i {1:s}/%04d.jpg -vcodec libx264 -b:v 2000k -pix_fmt yuv420p -movflags +faststart {2:s}/allsky-{3:s}.mp4'.format(25, seqfolder, imgfolder, timespec).split()
        #process = subprocess.run(cmd)


        # delete all existing symlinks in seqfolder
        rmlinks = list(filter(os.path.islink, Path(seqfolder).iterdir()))
        if rmlinks:
            logger.warning('Removing existing symlinks in %s', seqfolder)
            for f in rmlinks:
                os.unlink(f)


        # remove sequence folder
        try:
            os.rmdir(seqfolder)
        except OSError as e:
            logger.error('Cannote remove sequence folder: %s', str(e))


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'action',
        help='action',
        choices=('run', 'darks', 'avconv'),
    )
    argparser.add_argument(
        '--timespec',
        '-t',
        help='time spec',
        type=str,
    )

    args = argparser.parse_args()
    it = IndiTimelapse()

    args_list = list()
    if args.timespec:
        args_list.append(args.timespec)

    action_func = getattr(it, args.action)
    action_func(*args_list)


