#!/usr/bin/env python

import sys
import time
import logging
from datetime import datetime
import copy

from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Value
from multiprocessing import current_process
from multiprocessing import log_to_stderr

import PyIndi
from astropy.io import fits
import cv2
import numpy

#import PythonMagick

#CCD_NAME       = "CCD Simulator"
#CCD_NAME       = "ZWO CCD ASI290MM"
CCD_NAME       = "SVBONY SV305 0"

CCD_BINNING         = 1          # binning
EXPOSURE_PERIOD     =  5.00000   # time between beginning of each frame
CCD_GAIN            = 100        # gain

CCD_EXPOSURE_MAX    = 15.00000
CCD_EXPOSURE_MIN    =  0.00003
CCD_EXPOSURE_DEF    =  1.00000

TARGET_MEAN         = 40
TARGET_MEAN_MAX     = TARGET_MEAN + 10
TARGET_MEAN_MIN     = TARGET_MEAN - 10


logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

logger = log_to_stderr()
logger.setLevel(logging.INFO)


class IndiClient(PyIndi.BaseClient):
 
    def __init__(self):
        super(IndiClient, self).__init__()
        self.device = None
        self.logger = logging.getLogger('PyQtIndi.IndiClient')
        self.logger.info('creating an instance of PyQtIndi.IndiClient')

        self.img_q = Queue()
        self.exposure_v = Value('f', copy.copy(CCD_EXPOSURE_DEF))

        self.logger.info('Starting ImageProcessorWorker process')
        self.img_process = ImageProcessorWorker(self.img_q, self.exposure_v)
        self.img_process.start()


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



        if pName == "CCD_EXPOSURE":
            # take first exposure
            self.takeExposure()
        elif pName == "CCD_TEMPERATURE":
            temp = self.device.getNumber("CCD_TEMPERATURE")
            self.logger.info("Temperature: %d", temp[0].value)
        elif pName == "CCD_BINNING":
            binmode = self.device.getNumber("CCD_BINNING")
            binmode[0].value = CCD_BINNING
            self.sendNewNumber(binmode)
        elif pName == "CCD_GAIN":
            ccdgain = self.device.getNumber("CCD_GAIN")
            ccdgain[0].value = CCD_GAIN
            self.sendNewNumber(ccdgain)



    def removeProperty(self, p):
        self.logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        self.logger.info("new BLOB %s", bp.name)
        ### get image data
        imgdata = bp.getblobdata()

        ### process data in worker
        self.img_q.put(imgdata)

        sleeptime = float(EXPOSURE_PERIOD) - float(self.exposure_v.value)
        self.logger.info('...Sleeping for %0.6f seconds...', sleeptime)
        time.sleep(sleeptime)

        ### start new exposure
        self.takeExposure()


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


    def takeExposure(self):
        self.logger.info("Taking %0.6f second exposure", float(self.exposure_v.value))
        #get current exposure time
        exp = self.device.getNumber("CCD_EXPOSURE")
        # set exposure time to 5 seconds
        exp[0].value = float(self.exposure_v.value)
        # send new exposure time to server/device
        self.sendNewNumber(exp)




class ImageProcessorWorker(Process):
    def __init__(self, img_q, exposure_v):
        super(ImageProcessorWorker, self).__init__()

        self.img_q = img_q
        self.exposure_v = exposure_v


        self.dark = fits.open('dark_7s.fit')


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

            scidata_calibrated = self.calibrate(scidata_uncalibrated)
            scidata_color = self.colorize(scidata_calibrated)
            self.write_jpg(scidata_color)

            self.calculate_exposure(scidata_color)


    def write_fit(self, hdulist):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        hdulist.writeto("{0}.fit".format(now_str))

        logger.info('Finished writing fit file')


    def write_jpg(self, scidata):
        now_str = datetime.now().strftime('%y%m%d_%H%M%S')

        cv2.imwrite("{0}_wb.jpg".format(now_str), scidata, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #cv2.imwrite("{0}_rgb.png".format(now_str), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite("{0}_wb.png".format(now_str), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite("{0}_rgb.tif".format(now_str), scidata)


        ### ImageMagick ###
        ### write image data to BytesIO buffer
        #blobfile = io.BytesIO(self.imgdata)

        #with open("frame.fit", "wb") as f:
        #    f.write(blobfile.getvalue())

        #i = PythonMagick.Image("frame.fit")
        #i.magick('TIF')
        #i.write('frame.tif')

        logger.info('Finished writing files')


    def calibrate(self, scidata_uncalibrated):

        scidata = cv2.subtract(scidata_uncalibrated, self.dark[0].data)
        return scidata


    def colorize(self, scidata):

        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_BG2BGR)
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_GB2BGR)
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_BG2RGB)
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_RG2RGB)
        ###

        ###
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BayerGR2RGB)
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_GR2RGB)
        #scidata_rgb = self._convert_GRGB_to_RGB_8bit(scidata)
        ###

        ### seems to work best for GRBG
        #scidata_rgb = cv2.cvtColor(scidata, cv2.COLOR_BAYER_GR2BGR)
        scidata_rgb = self._convert_GRBG_to_RGB_8bit(scidata)

        #scidata_wb = self.white_balance(scidata_rgb)
        scidata_wb = self.white_balance2(scidata_rgb)

        #if self.roi is not None:
        #    scidata = scidata[self.roi[1]:self.roi[1]+self.roi[3], self.roi[0]:self.roi[0]+self.roi[2]]
        #hdulist[0].data = scidata

        return scidata_wb


    def calculate_exposure(self, data_bytes):
        r, g, b = cv2.split(data_bytes)
        r_avg = cv2.mean(r)[0]
        g_avg = cv2.mean(g)[0]
        b_avg = cv2.mean(b)[0]

        logger.info('R mean: %0.2f', r_avg)
        logger.info('G mean: %0.2f', g_avg)
        logger.info('B mean: %0.2f', b_avg)

         # Find the gain of each channel
        k = (r_avg + g_avg + b_avg) / 3

        logger.info('Current average: %0.2f', k)

        current_exposure = self.exposure_v.value
        if g_avg > TARGET_MEAN_MAX:
            #new_exposure = current_exposure / 2.0
            new_exposure = current_exposure / ( g_avg / float(TARGET_MEAN) )
        else:
            #new_exposure = current_exposure + 1
            new_exposure = current_exposure * ( float(TARGET_MEAN) / g_avg )


        if new_exposure < CCD_EXPOSURE_MIN:
            new_exposure = CCD_EXPOSURE_MIN
        elif new_exposure > CCD_EXPOSURE_MAX:
            new_exposure = CCD_EXPOSURE_MAX


        logger.warning('New exposure: %0.6f', new_exposure)
        self.exposure_v.value = new_exposure



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


    def white_balance(self, data_bytes):
        ### This method does not work very well
        result = cv2.cvtColor(data_bytes, cv2.COLOR_BGR2LAB)
        avg_a = numpy.average(result[:, :, 1])
        avg_b = numpy.average(result[:, :, 2])
        result[:, :, 1] = result[:, :, 1] - ((avg_a - 128) * (result[:, :, 0] / 255.0) * 1.1)
        result[:, :, 2] = result[:, :, 2] - ((avg_b - 128) * (result[:, :, 0] / 255.0) * 1.1)
        data = cv2.cvtColor(result, cv2.COLOR_LAB2BGR)
        return data


    def _convert_GRGB_to_RGB_8bit(self, data_bytes):
        data_bytes = numpy.frombuffer(data_bytes, dtype=numpy.uint8)
        even = data_bytes[0::2]
        odd = data_bytes[1::2]
        # Convert bayer16 to bayer8
        bayer8_image = (even >> 4) | (odd << 4)
        bayer8_image = bayer8_image.reshape((1080, 1920))
        # Use OpenCV to convert Bayer GRGB to RGB
        return cv2.cvtColor(bayer8_image, cv2.COLOR_BayerGR2RGB)


    def _convert_GRBG_to_RGB_8bit(self, data_bytes):
        data_bytes = numpy.frombuffer(data_bytes, dtype=numpy.uint8)
        even = data_bytes[0::2]
        odd = data_bytes[1::2]
        # Convert bayer16 to bayer8
        bayer8_image = (even >> 4) | (odd << 4)
        bayer8_image = bayer8_image.reshape((1080, 1920))
        # Use OpenCV to convert Bayer GRBG to RGB
        return cv2.cvtColor(bayer8_image, cv2.COLOR_BayerGR2BGR)



if __name__ == "__main__":
    # instantiate the client
    indiclient = IndiClient()

    # set roi
    #indiclient.roi = (270, 200, 700, 700) # region of interest for my allsky cam

    # set indi server localhost and port 7624
    indiclient.setServer("localhost", 7624)

    # connect to indi server
    print("Connecting to indiserver")
    if (not(indiclient.connectServer())):
         print("No indiserver running on {0}:{1} - Try to run".format(indiclient.getHost(), indiclient.getPort()))
         print("  indiserver indi_simulator_telescope indi_simulator_ccd")
         sys.exit(1)
      
    # start endless loop, client works asynchron in background
    while True:
        time.sleep(1)



