#!/usr/bin/env python3


import board
import digitalio
import time
import signal
import logging

import threading
from multiprocessing import Process
from multiprocessing import Value
from multiprocessing import log_to_stderr

PIN = 'D21'


LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s/%(threadName)s: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger = log_to_stderr()
logger.handlers.clear()
logger.addHandler(LOG_HANDLER_STREAM)
logger.setLevel(logging.INFO)


class GpioWorkerProcess(Process):

    def __init__(self, idx, stopper_v):
        super(GpioWorkerProcess, self).__init__()

        self.stopper_v = stopper_v
        self.name = 'GpioWorkerProcess-{0:03d}'.format(idx)

        self.pin = None


    def sigint_handler_worker(self, signum, frame):
        # ignore SIGINT
        pass


    def run(self):
        logger.warning('Starting worker')

        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGINT, self.sigint_handler_worker)


        logger.info('Initializing GPIO %s', PIN)
        p = getattr(board, PIN)
        self.pin = digitalio.DigitalInOut(p)
        self.pin.direction = digitalio.Direction.OUTPUT


        while True:
            if self.stopper_v.value:
                logger.warning('Stopping')
                self.pin.deinit()
                return


            self.pin.value = 1


            time.sleep(1)


class GpioWorkerThread(threading.Thread):

    def __init__(self, idx, stopper_v):
        super(GpioWorkerThread, self).__init__()

        self.threadID = idx
        self.stopper_v = stopper_v
        self.name = 'GpioWorkerThread-{0:03d}'.format(idx)

        self.pin = None


    def run(self):
        logger.warning('Starting worker')


        logger.info('Initializing GPIO %s', PIN)
        p = getattr(board, PIN)
        self.pin = digitalio.DigitalInOut(p)
        self.pin.direction = digitalio.Direction.OUTPUT


        while True:
            if self.stopper_v.value:
                logger.warning('Stopping')
                self.pin.deinit()
                return


            self.pin.value = 1


            time.sleep(1)


class TestWorkerProcess(Process):
    def __init__(self, idx, stopper_v):
        super(TestWorkerProcess, self).__init__()

        self.stopper_v = stopper_v
        self.name = 'TestWorkerProcess-{0:d}'.format(idx)


    def sigint_handler_worker(self, signum, frame):
        # ignore SIGINT
        pass


    def run(self):
        logger.warning('Starting worker')

        # setup signal handling after detaching from the main process
        signal.signal(signal.SIGINT, self.sigint_handler_worker)


        while True:
            if self.stopper_v.value:
                return

            # process does nothing other than exist
            time.sleep(1)


class GpioLockTest(object):

    def __init__(self):
        self.gpio_worker = None
        self.gpio_worker_idx = 0

        self.test_worker_process = None
        self.test_worker_process_idx = 0

        self.stopper_v = Value('i', 0)  # set to 1 to shutdown processes

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


                # reset stopper
                with self.stopper_v.get_lock():
                    self.stopper_v.value = 0


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


        ### swap these to switch between threads and processes
        self.gpio_worker = GpioWorkerThread(self.gpio_worker_idx, self.stopper_v)
        #self.gpio_worker = GpioWorkerProcess(self.gpio_worker_idx, self.stopper_v)


        self.gpio_worker.start()


    def stopGpioWorker(self):
        if not self.gpio_worker:
            return

        if not self.gpio_worker.is_alive():
            return

        logger.info('Stopping GpioWorker')

        with self.stopper_v.get_lock():
            self.stopper_v.value = 1

        self.gpio_worker.join()


    def startTestWorkerProcess(self):
        if self.test_worker_process:
            if self.test_worker_process.is_alive():
                return

        self.test_worker_process_idx += 1
        self.test_worker_process = TestWorkerProcess(self.test_worker_process_idx, self.stopper_v)
        self.test_worker_process.start()


    def stopTestWorkerProcess(self):
        if not self.test_worker_process:
            return

        if not self.test_worker_process.is_alive():
            return

        logger.info('Terminating TestWorkerProcess')

        with self.stopper_v.get_lock():
            self.stopper_v.value = 1

        self.test_worker_process.join()


if __name__ == "__main__":
    t = GpioLockTest().main()

