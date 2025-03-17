#!/usr/bin/env python3

# for logging
import sys
import time
import logging
import PyIndi
from pprint import pformat
from pprint import pprint

# Fancy printing of INDI states
# Note that all INDI constants are accessible from the module as PyIndi.CONSTANTNAME
def strISState(s):
    if s == PyIndi.ISS_OFF:
        return "Off"
    else:
        return "On"
def strIPState(s):
    if s == PyIndi.IPS_IDLE:
        return "Idle"
    elif s == PyIndi.IPS_OK:
        return "Ok"
    elif s == PyIndi.IPS_BUSY:
        return "Busy"
    elif s == PyIndi.IPS_ALERT:
        return "Alert"

# The IndiClient class which inherits from the module PyIndi.BaseClient class
# It should implement all the new* pure virtual functions.
class IndiClient(PyIndi.BaseClient):
    def __init__(self):
        super(IndiClient, self).__init__()
        self.logger = logging.getLogger('IndiClient')
        self.logger.info('creating an instance of IndiClient')
    def newDevice(self, d):
        self.logger.info("new device " + d.getDeviceName())
    def newProperty(self, p):
        self.logger.info("new property "+ p.getName() + " for device "+ p.getDeviceName())
        v = self.getDeviceByName(p.getDeviceName()).getNumber(p.getName())
        if type(v) is PyIndi.PropertyViewNumber:
            ctl = self.get_control(v.getName(), 'number', p.getDeviceName())
            for i, c in enumerate(ctl):
                self.logger.info(' Index %d: %s', i, c.name)  # useful to find value names
                self.logger.info('  current %d, min %d, max %d, step %d, format: %s', c.value, c.min, c.max, c.step, c.format)
        else:
            self.logger.info(' Value %s', str(self.getDeviceByName(p.getDeviceName()).getNumber(p.getName())))  # useful to find value names
    def removeProperty(self, p):
        self.logger.info("remove property "+ p.getName() + " for device "+ p.getDeviceName())
    def newBLOB(self, bp):
        self.logger.info("new BLOB "+ bp.name)
    def newSwitch(self, svp):
        self.logger.info ("new Switch "+ svp.name + " for device "+ svp.device)
        ctl = self.get_control(svp.name, 'switch', svp.device)
        for i, c in enumerate(ctl):
            self.logger.info(' Index %d: %s %s', i, c.name, c.getState())  # useful to find value names
    def newNumber(self, nvp):
        self.logger.info("new Number "+ nvp.name + " for device "+ nvp.device)
        ctl = self.get_control(nvp.name, 'number', nvp.device)
        for i, c in enumerate(ctl):
            self.logger.info(' Index %d: %s', i, c.name)  # useful to find value names
            self.logger.info('  current %d, min %d, max %d, step %d, format: %s', c.value, c.min, c.max, c.step, c.format)
    def newText(self, tvp):
        self.logger.info("new Text "+ tvp.name + " for device "+ tvp.device)
        #ctl = self.get_control(tvp.name, 'switch', tvp.device)
        #for i, c in enumerate(ctl):
        #    self.logger.info(' Value %d: %s', i, c.name)  # useful to find value names
    def newLight(self, lvp):
        self.logger.info("new Light "+ lvp.name + " for device "+ lvp.device)
    def newMessage(self, d, m):
        self.logger.info("new Message "+ d.messageQueue(m))
    def serverConnected(self):
        self.logger.info("Server connected ("+self.getHost()+":"+str(self.getPort())+")")
    def serverDisconnected(self, code):
        self.logger.info("Server disconnected (exit code = "+str(code)+","+str(self.getHost())+":"+str(self.getPort())+")")


    def get_control(self, name, ctl_type, deviceName, timeout=1.0):
        if timeout is None:
            timeout = self._timeout

        device = self.getDeviceByName(deviceName)

        ctl = None
        attr = {
            'number'  : 'getNumber',
            'switch'  : 'getSwitch',
            'text'    : 'getText',
            'light'   : 'getLight',
            'blob'    : 'getBLOB'
        }[ctl_type]

        started = time.time()
        while not(ctl):
            ctl = getattr(device, attr)(name)

            if not ctl and 0 < timeout < time.time() - started:
                raise TimeOutException('Timeout finding control {0}'.format(name))

            time.sleep(0.01)

        return ctl

    def __control2dict(self, control_name, control_type, transform, control=None):
        def get_dict(element):
            dest = {'name': element.name, 'label': element.label}
            dest.update(transform(element))
            return dest

        control = control if control else self.get_control(control_name, control_type)

        return [get_dict(c) for c in control]

    def values(self, ctl_name, ctl_type):
        return dict(map(lambda c: (c.name, c.value), self.get_control(ctl_name, ctl_type)))

    def switch_values(self, name, ctl=None):
        return self.__control2dict(name, 'switch', lambda c: {'value': c.getState() == PyIndi.ISS_ON}, ctl)

    def number_values(self, name, ctl=None):
        return self.__control2dict(name, 'text', lambda c: {'value': c.value, 'min': c.min, 'max': c.max, 'step': c.step, 'format': c.format}, ctl)

    def getDeviceByName(self, deviceName):
        for device in self.getDevices():
            if deviceName == device.getDeviceName():
                return device

        raise Exception('No device by name %s', deviceName)

logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

# Create an instance of the IndiClient class and initialize its host/port members
indiclient=IndiClient()
indiclient.setServer("localhost",7624)

# Connect to server
print("Connecting and waiting 1 sec")
if (not(indiclient.connectServer())):
     print("No indiserver running on "+indiclient.getHost()+":"+str(indiclient.getPort())+" - Try to run")
     print("  indiserver indi_simulator_telescope indi_simulator_ccd")
     sys.exit(1)
time.sleep(1)

print("List of devices")
dl=indiclient.getDevices()
for dev in dl:
    dev_name = dev.getDeviceName()
    print(dev_name)


# Disconnect from the indiserver
print("Disconnecting")
indiclient.disconnectServer()
