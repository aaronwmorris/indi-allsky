#!/usr/bin/env python3


import time
import signal
import logging

import threading
from multiprocessing import Process
from multiprocessing import log_to_stderr

PIN = 'D21'


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s/%(threadName)s: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger = log_to_stderr()
logger.handlers.clear()
logger.addHandler(LOG_HANDLER_STREAM)
logger.setLevel(logging.INFO)


class GpioWorker(threading.Thread):

    def __init__(self, idx):
        super(GpioWorker, self).__init__()

        import board
        import digitalio


        self.threadID = idx
        self.name = 'GpioWorker{0:03d}'.format(idx)


        logger.info('Initializing GPIO %s', PIN)
        p = getattr(board, PIN)
        self.pin = digitalio.DigitalInOut(p)
        self.pin.direction = digitalio.Direction.OUTPUT


        self._stopper = threading.Event()


    def stop(self):
        self._stopper.set()


    def stopped(self):
        return self._stopper.is_set()


    def run(self):
        logger.info('Running...')

        while True:
            if self.stopped():
                logger.warning('Stopping')
                self.pin.deinit()
                return


            self.pin.value = 1


            time.sleep(1)


class TestWorkerProcess(Process):
    def __init__(self, idx):
        super(TestWorkerProcess, self).__init__()

        self.name = 'TestWorkerProcess-{0:d}'.format(idx)

        self._shutdown = False


    def sigint_handler_worker(self, signum, frame):
        # ignore SIGINT
        pass


    def sigterm_handler_worker(self, signum, frame):
        logger.warning('Caught TERM signal')

        # set flag for program to stop processes
        self._shutdown = True


    def run(self):
        logger.info('Running...')
        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGTERM, self.sigterm_handler_worker)
        signal.signal(signal.SIGINT, self.sigint_handler_worker)


        while True:
            if self._shutdown:
                return

            # process does nothing other than exist
            time.sleep(1)


class GpioLockTest(object):

    def __init__(self):
        self.gpio_worker = None
        self.gpio_worker_idx = 0

        self.test_worker_process = None
        self.test_worker_process_idx = 0

        self._restart = False


    def sigint_handler_main(self, signum, frame):
        logger.warning('Caught SIGINT, restarting processes/threads')
        self._restart = True


    def main(self):
        signal.signal(signal.SIGINT, self.sigint_handler_main)

        logger.warning('*** Ctrl-c (SIGINT) to restart processes ***')
        logger.warning('*** Ctrl-backslash (SIGTERM) to exit ***')


        while True:
            if self._restart:
                self._restart = False
                self.stopTestWorkerProcess()
                self.stopGpioWorker()
                time.sleep(1)


            ### starting the process worker before the threaded GPIO worker causes a locked gpio when the GPIO worker is restarted
            self.startTestWorkerProcess()
            self.startGpioWorker()
            ###

            ### no locked pin here
            #self.startGpioWorker()
            #self.startTestWorkerProcess()
            ###

            time.sleep(3)


    def startGpioWorker(self):
        if self.gpio_worker:
            if self.gpio_worker.is_alive():
                return


        self.gpio_worker_idx += 1

        logger.info('Starting GpioWorker-%d worker', self.gpio_worker_idx)
        self.gpio_worker = GpioWorker(self.gpio_worker_idx)
        self.gpio_worker.start()


    def stopGpioWorker(self):
        if not self.gpio_worker:
            return

        if not self.gpio_worker.is_alive():
            return

        logger.info('Stopping GpioWorker')

        self.gpio_worker.stop()
        self.gpio_worker.join()


    def startTestWorkerProcess(self):
        if self.test_worker_process:
            if self.test_worker_process.is_alive():
                return

        self.test_worker_process_idx += 1
        logger.info('Starting TestWorkerProcess-%d worker', self.test_worker_process_idx)
        self.test_worker_process = TestWorkerProcess(self.test_worker_process_idx)
        self.test_worker_process.start()


    def stopTestWorkerProcess(self):
        if not self.test_worker_process:
            return

        if not self.test_worker_process.is_alive():
            return

        logger.info('Terminating TestWorkerProcess')
        self.test_worker_process.terminate()
        self.test_worker_process.join()



if __name__ == "__main__":
    t = GpioLockTest().main()

