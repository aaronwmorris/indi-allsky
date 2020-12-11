#!/usr/bin/env python

import sys
import time
import logging
import PyIndi

#CCD_NAME       = "CCD Simulator"
CCD_NAME       = "ZWO CCD ASI290MM"
CCD_EXPOSURE   = 5


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
        self.logger.info("new property %s for device %s", p.getName(), p.getDeviceName())
        if self.device is not None and p.getName() == "CONNECTION" and p.getDeviceName() == self.device.getDeviceName():
            self.logger.info("Got property CONNECTION for %s!", CCD_NAME)
            # connect to device
            self.connectDevice(self.device.getDeviceName())
            # set BLOB mode to BLOB_ALSO
            self.setBLOBMode(1, self.device.getDeviceName(), None)


        pName = p.getName()

        if pName == "CCD_EXPOSURE":
            # take first exposure
            self.takeExposure()
        elif pName == "CCD_TEMPERATURE":
            temp = self.device.getNumber("CCD_TEMPERATURE")
            self.logger.info("Temperature: %d", temp[0].value)


    def removeProperty(self, p):
        self.logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        self.logger.info("new BLOB %s", bp.name)
        # get image data
        img = bp.getblobdata()
        # write image data to BytesIO buffer
        import io
        blobfile = io.BytesIO(img)
        # open a file and save buffer to disk
        with open("frame.fit", "wb") as f:
            f.write(blobfile.getvalue())
        # start new exposure
        self.takeExposure()


    def newSwitch(self, svp):
        self.logger.info ("new Switch %s for device %s", svp.name, svp.device)


    def newNumber(self, nvp):
        self.logger.info("new Number %s for device %s", nvp.name, nvp.device)


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
        self.logger.info(">>>>>>>>")
        #get current exposure time
        exp = self.device.getNumber("CCD_EXPOSURE")
        # set exposure time to 5 seconds
        exp[0].value = CCD_EXPOSURE
        # send new exposure time to server/device
        self.sendNewNumber(exp)
  

if __name__ == "__main__":
    # instantiate the client
    indiclient=IndiClient()
    # set indi server localhost and port 7624
    indiclient.setServer("localhost",7624)
    # connect to indi server
    print("Connecting to indiserver")
    if (not(indiclient.connectServer())):
         print("No indiserver running on {0}:{1} - Try to run".format(indiclient.getHost(), indiclient.getPort()))
         print("  indiserver indi_simulator_telescope indi_simulator_ccd")
         sys.exit(1)
      
    # start endless loop, client works asynchron in background
    while True:
        time.sleep(1)
