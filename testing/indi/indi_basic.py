#!/usr/bin/env python3

import PyIndi
import time
import sys
import logging


CCD = "CCD Simulator"

INDI_SERVER = "localhost"
INDI_PORT = 7624



logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)



class IndiClient(PyIndi.BaseClient):
    def __init__(self):
        super(IndiClient, self).__init__()

        pyindi_version = '.'.join((
            str(getattr(PyIndi, 'INDI_VERSION_MAJOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_MINOR', -1)),
            str(getattr(PyIndi, 'INDI_VERSION_RELEASE', -1)),
        ))

        logger.info("INDI version: %s", pyindi_version)


    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def removeDevice(self, d):
        logger.info("removed device %s", d.getDeviceName())

    def newProperty(self, p):
        pass

    def removeProperty(self, p):
        pass

    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)

    def newSwitch(self, svp):
        pass

    def newNumber(self, nvp):
        pass

    def newText(self, tvp):
        pass

    def newLight(self, lvp):
        pass

    def newMessage(self, d, m):
        pass

    def serverConnected(self):
        pass

    def serverDisconnected(self, code):
        pass


# connect to the server
indiclient = IndiClient()
indiclient.setServer(INDI_SERVER, INDI_PORT)

logger.info("Connecting to indiserver")
if not (indiclient.connectServer()):
    logger.error(
        "No indiserver running on %s:%d",
        indiclient.getHost(),
        indiclient.getPort()
    )
    sys.exit(1)


### Connect the CCD
device_ccd = None
while not device_ccd:
    logger.info("Connecting to %s", CCD)
    device_ccd = indiclient.getDevice(CCD)
    time.sleep(0.5)

connection = None
while not connection:
    logger.info("Get CONNECTION control")
    connection = device_ccd.getSwitch("CONNECTION")
    time.sleep(0.5)

if not device_ccd.isConnected():
    connection[0].setState(PyIndi.ISS_ON)   # CONNECT
    connection[1].setState(PyIndi.ISS_OFF)  # DISCONNECT
    indiclient.sendNewSwitch(connection)


while not device_ccd.isConnected():
    logger.warning('Waiting on ccd connection')
    time.sleep(0.5)

logger.info("ccd connected")



### Number control test
equatorial_pe = None
while not equatorial_pe:
    logger.info("Get EQUITORIAL_PE control (number)")
    equatorial_pe = device_ccd.getNumber("EQUATORIAL_PE")
    time.sleep(0.5)


logger.info("Set EQUATORIAL_PE to M13")

equatorial_pe[0].setValue(16.7175)  # RA_PE
equatorial_pe[1].setValue(36.4233)  # DEC_PE
indiclient.sendNewNumber(equatorial_pe)



### Text control test
ccd_directory_location = None
while not ccd_directory_location:
    logger.info("Get CCD_DIRECTORY_LOCATION control (text)")
    ccd_directory_location = device_ccd.getText("CCD_DIRECTORY_LOCATION")
    time.sleep(0.5)


logger.info("Set CCD_DIRECTORY_LOCATION to /tmp")

ccd_directory_location[0].setText("/tmp")  # LOCATION
indiclient.sendNewText(ccd_directory_location)



### Switch control test
simulate_bayer = None
while not simulate_bayer:
    logger.info("Get SIMULATE_BAYER control (switch)")
    simulate_bayer = device_ccd.getSwitch("SIMULATE_BAYER")
    time.sleep(0.5)


logger.info("Set SIMULATE_BAYER to Enable")

simulate_bayer[0].setState(PyIndi.ISS_ON)   # INDI_ENABLED
simulate_bayer[1].setState(PyIndi.ISS_OFF)  # INDI_DISABLED
indiclient.sendNewSwitch(simulate_bayer)


