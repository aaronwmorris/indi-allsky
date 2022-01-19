import time
from multiprocessing import Process
#from threading import Thread
import queue
import logging

from . import filetransfer

logger = logging.getLogger('indi_allsky')


class FileUploader(Process):
    def __init__(self, idx, config, upload_q):
        super(FileUploader, self).__init__()

        #self.threadID = idx
        self.name = 'FileUploader{0:03d}'.format(idx)

        self.config = config

        self.upload_q = upload_q


    def run(self):
        while True:
            time.sleep(1.0)  # sleep every loop

            try:
                u_dict = self.upload_q.get_nowait()
            except queue.Empty:
                continue


            if u_dict.get('stop'):
                return

            local_file = u_dict['local_file']
            remote_file = u_dict['remote_file']

            try:
                client_class = getattr(filetransfer, self.config['FILETRANSFER']['CLASSNAME'])
            except AttributeError:
                logger.error('Unknown filetransfer class: %s', self.config['FILETRANSFER']['CLASSNAME'])
                return


            client = client_class(timeout=self.config['FILETRANSFER']['TIMEOUT'])


            start = time.time()

            try:
                client.connect(
                    self.config['FILETRANSFER']['HOST'],
                    self.config['FILETRANSFER']['USERNAME'],
                    self.config['FILETRANSFER']['PASSWORD'],
                    port=self.config['FILETRANSFER']['PORT'],
                )
            except filetransfer.exceptions.ConnectionFailure as e:
                logger.error('Connection failure: %s', e)
                client.close()
                return
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                return


            # Upload file
            try:
                client.put(local_file, remote_file)
            except filetransfer.exceptions.ConnectionFailure as e:
                logger.error('Connection failure: %s', e)
                client.close()
                return
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                return
            except filetransfer.exceptions.TransferFailure as e:
                logger.error('Tranfer failure: %s', e)
                client.close()
                return
            except filetransfer.exceptions.PermissionFailure as e:
                logger.error('Permission failure: %s', e)
                client.close()
                return


            # close file transfer client
            client.close()

            upload_elapsed_s = time.time() - start
            logger.info('Upload transaction completed in %0.4f s', upload_elapsed_s)



            #raise Exception('Testing uncaught exception')

