#!/usr/bin/env python

import sys
import time
import logging
from datetime import datetime
from threading import Thread

import PyIndi
from astropy.io import fits
import cv2

#import PythonMagick

CCD_NAME       = "CCD Simulator"
#CCD_NAME       = "ZWO CCD ASI290MM"

EXPOSURE_PERIOD     = 7.5    # time between beginning of each frame
CCD_EXPOSURE        = 5.0    # length of exposure
CCD_BINNING         = 1      # binning


logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
 
  
class IndiClient(PyIndi.BaseClient):
 
    device = None
 
    def __init__(self):
        super(IndiClient, self).__init__()
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



    def removeProperty(self, p):
        self.logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        self.logger.info("new BLOB %s", bp.name)
        ### get image data
        imgdata = bp.getblobdata()

        ### process data in new Thread
        ImageProcessorThread(imgdata).start()

        sleeptime = float(EXPOSURE_PERIOD) - float(CCD_EXPOSURE)
        self.logger.info('...Sleeping for %0.2f seconds...', sleeptime)
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
        self.logger.info("Taking %0.2f second exposure", float(CCD_EXPOSURE))
        #get current exposure time
        exp = self.device.getNumber("CCD_EXPOSURE")
        # set exposure time to 5 seconds
        exp[0].value = float(CCD_EXPOSURE)
        # send new exposure time to server/device
        self.sendNewNumber(exp)


class ImageProcessorThread(Thread):
    def __init__(self, imgdata):
        # Call the Thread class's init function
        super(ImageProcessorThread, self).__init__()

        self.imgdata = imgdata


    def run(self):
        import io

        ### OpenCV ###
        blobfile = io.BytesIO(self.imgdata)
        hdulist = fits.open(blobfile)
        scidata = hdulist[0].data
        #if self.roi is not None:
        #    scidata = scidata[self.roi[1]:self.roi[1]+self.roi[3], self.roi[0]:self.roi[0]+self.roi[2]]
        #hdulist[0].data = scidata
        hdulist.writeto("{0}.fit".format(datetime.now()))

        #cv2.imwrite("{0}.png".format(datetime.now()), scidata, [cv2.IMWRITE_JPEG_QUALITY, 90])
        #cv2.imwrite("{0}.jpg".format(datetime.now()), scidata, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite("{0}.tif".format(datetime.now()), scidata)


        ### ImageMagick ###
        ### write image data to BytesIO buffer
        #blobfile = io.BytesIO(self.imgdata)

        #with open("frame.fit", "wb") as f:
        #    f.write(blobfile.getvalue())

        #i = PythonMagick.Image("frame.fit")
        #i.magick('TIF')
        #i.write('frame.tif')




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
