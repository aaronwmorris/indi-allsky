
import signal
import logging
import traceback


from multiprocessing import Process
#from threading import Thread
#import queue

from .exceptions import TimeOutException

logger = logging.getLogger('indi_allsky')


class CaptureWorker(Process):
    def __init__(
        self,
        idx,
        config,
        error_q,
    ):

        super(CaptureWorker, self).__init__()

        #self.threadID = idx
        self.name = 'ImageWorker{0:03d}'.format(idx)

        self.config = config
        self.error_q = error_q


    def sighup_handler_worker(self, signum, frame):
        logger.warning('Caught HUP signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigterm_handler_worker(self, signum, frame):
        logger.warning('Caught TERM signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigint_handler_worker(self, signum, frame):
        logger.warning('Caught INT signal')

        # set flag for program to stop processes
        self._shutdown = True


    def sigalarm_handler_worker(self, signum, frame):
        raise TimeOutException()


    def run(self):
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGHUP, self.sighup_handler_worker)
        signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        signal.signal(signal.SIGINT, self.sigint_handler_worker)
        signal.signal(signal.SIGALRM, self.sigalarm_handler_worker)


        ### use this as a method to log uncaught exceptions
        try:
            self.saferun()
        except Exception as e:
            tb = traceback.format_exc()
            self.error_q.put((str(e), tb))
            raise e



    def saferun(self):
        #raise Exception('Test exception handling in worker')
        pass


