#!/usr/bin/env python3

import os
import time
import dbus
from dbus.mainloop.glib import DBusGMainLoop
import logging

logging.basicConfig(level=logging.INFO)
logger = logging


myDevices = [ "indi_simulator_telescope", "indi_simulator_ccd" ]


DBusGMainLoop(set_as_default=True)


# Create a session bus.
bus = dbus.SessionBus()


# Create an object that will proxy for a particular remote object.
remote_object = bus.get_object(
    "org.kde.kstars",  # Connection name
    "/KStars/INDI"  # Object's path
)


# Introspection returns an XML document containing information
# about the methods supported by an interface.
logger.info("Introspection data: %s", remote_object.Introspect())

# Get INDI interface
iface = dbus.Interface(remote_object, 'org.kde.kstars.INDI')

# Start INDI devices
iface.start(7624, myDevices)

logger.info("Waiting for INDI devices...")

# Create array for received devices
devices = []

while True:
    devices = iface.getDevices()
    if len(devices) < len(myDevices):
        time.sleep(1)
    else:
        break

logger.info("We received the following devices:")
for device in devices:
    logger.info(device)

logger.info("Establishing connection to Telescope and CCD...")

# Set connect switch to ON to connect the devices
iface.setSwitch("Telescope Simulator", "CONNECTION", "CONNECT", "On")
# Send the switch to INDI server so that it gets processed by the driver
iface.sendProperty("Telescope Simulator", "CONNECTION")
# Same thing for CCD Simulator
iface.setSwitch("CCD Simulator", "CONNECTION", "CONNECT", "On")
iface.sendProperty("CCD Simulator", "CONNECTION")

telescopeState = "Busy"
ccdState       = "Busy"

# Wait until devices are connected
while True:
    telescopeState = iface.getPropertyState("Telescope Simulator", "CONNECTION")
    ccdState       = iface.getPropertyState("CCD Simulator", "CONNECTION")
    if telescopeState != "Ok" or ccdState != "Ok":
        time.sleep(1)
    else:
        break

logger.info("Connection to Telescope and CCD is established.")



logger.info("Commanding telescope to slew to coordinates of star Caph...")

# Set Telescope RA,DEC coords in JNOW
iface.setNumber("Telescope Simulator", "EQUATORIAL_EOD_COORD", "RA", 0.166)
iface.setNumber("Telescope Simulator", "EQUATORIAL_EOD_COORD", "DEC", 59.239)
iface.sendProperty("Telescope Simulator", "EQUATORIAL_EOD_COORD")

# Wait until slew is done
telescopeState = "Busy"
while True:
    telescopeState = iface.getPropertyState("Telescope Simulator", "EQUATORIAL_EOD_COORD")
    if telescopeState != "Ok":
        time.sleep(1)
    else:
        break

logger.info("Telescope slew is complete, tracking...")


logger.info("Taking a 5 second CCD exposure...")

# Take 5 second exposure
iface.setNumber("CCD Simulator", "CCD_EXPOSURE", "CCD_EXPOSURE_VALUE", 5.0)
iface.sendProperty("CCD Simulator", "CCD_EXPOSURE")

# Wait until exposure is done
ccdState = "Busy"
while True:
    ccdState = iface.getPropertyState("CCD Simulator", "CCD_EXPOSURE")
    if ccdState != "Ok":
        time.sleep(1)
    else:
        break

logger.info("Exposure complete")


# Get image file name and open it in external fv tool
fileinfo = iface.getBLOBFile("CCD Simulator", "CCD1", "CCD1")
logger.info("We received file: %s with format %s and size %d", fileinfo[0], fileinfo[1], fileinfo[2])

logger.info("Invoking fv tool to view the received FITS file...")
# run external fits viewer
command = "fv " + fileinfo[0]
os.system(command)

logger.info("Shutting down INDI server...")
# Stop INDI server
iface.stop("7624")
