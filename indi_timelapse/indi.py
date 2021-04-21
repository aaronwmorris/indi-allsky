import time
from datetime import datetime

import multiprocessing

import PyIndi


logger = multiprocessing.get_logger()


class IndiClient(PyIndi.BaseClient):
    def __init__(self, config, indiblob_status_send, img_q):
        super(IndiClient, self).__init__()

        self.config = config
        self.indiblob_status_send = indiblob_status_send
        self.img_q = img_q

        self._filename_t = '{0:s}'

        logger.info('creating an instance of IndiClient')

    @property
    def filename_t(self):
        return self._filename_t

    @filename_t.setter
    def filename_t(self, new_filename_t):
        self._filename_t = new_filename_t

    def newDevice(self, d):
        logger.info("new device %s", d.getDeviceName())

    def newProperty(self, p):
        #logger.info("new property %s for device %s", p.getName(), p.getDeviceName())
        pass

    def removeProperty(self, p):
        logger.info("remove property %s for device %s", p.getName(), p.getDeviceName())


    def newBLOB(self, bp):
        logger.info("new BLOB %s", bp.name)
        start = time.time()

        ### get image data
        imgdata = bp.getblobdata()

        elapsed_s = time.time() - start
        logger.info('Blob downloaded in %0.4f s', elapsed_s)

        self.indiblob_status_send.send(True)  # Notify main process next exposure may begin

        exp_date = datetime.now()

        ### process data in worker
        self.img_q.put((imgdata, exp_date, self._filename_t))


    def newSwitch(self, svp):
        logger.info("new Switch %s for device %s", svp.name, svp.device)

    def newNumber(self, nvp):
        #logger.info("new Number %s for device %s", nvp.name, nvp.device)
        pass

    def newText(self, tvp):
        logger.info("new Text %s for device %s", tvp.name, tvp.device)

    def newLight(self, lvp):
        logger.info("new Light %s for device %s", lvp.name, lvp.device)

    def newMessage(self, d, m):
        logger.info("new Message %s", d.messageQueue(m))

    def serverConnected(self):
        logger.info("Server connected (%s:%d)", self.getHost(), self.getPort())

    def serverDisconnected(self, code):
        logger.info("Server disconnected (exit code = %d, %s, %d", code, str(self.getHost()), self.getPort())



