import time
from datetime import timedelta
from pathlib import Path
import signal
import traceback
import logging

from multiprocessing import Process
#from threading import Thread
import queue

#from .flask import db
from .flask.miscDb import miscDb

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import NotificationCategory

from .flask.models import IndiAllSkyDbTaskQueueTable

from . import filetransfer

from sqlalchemy.orm.exc import NoResultFound

from .exceptions import TimeOutException


logger = logging.getLogger('indi_allsky')



class FileUploader(Process):
    def __init__(
        self,
        idx,
        config,
        error_q,
        upload_q,
    ):
        super(FileUploader, self).__init__()

        #self.threadID = idx
        self.name = 'FileUploader{0:03d}'.format(idx)

        self.config = config

        self._miscDb = miscDb(self.config)

        self.error_q = error_q
        self.upload_q = upload_q


        self._shutdown = False



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

        while True:
            try:
                u_dict = self.upload_q.get(timeout=31)  # prime number
            except queue.Empty:
                continue


            if u_dict.get('stop'):
                logger.warning('Goodbye')
                return

            if self._shutdown:
                logger.warning('Goodbye')
                return


            task_id = u_dict['task_id']


            try:
                task = IndiAllSkyDbTaskQueueTable.query\
                    .filter(IndiAllSkyDbTaskQueueTable.id == task_id)\
                    .filter(IndiAllSkyDbTaskQueueTable.state == TaskQueueState.QUEUED)\
                    .filter(IndiAllSkyDbTaskQueueTable.queue == TaskQueueQueue.UPLOAD)\
                    .one()

            except NoResultFound:
                logger.error('Task ID %d not found', task_id)
                continue


            task.setRunning()


            action = task.data['action']
            local_file = task.data.get('local_file')
            remote_file = task.data.get('remote_file')
            remove_local = task.data.get('remove_local')

            mq_data = task.data.get('mq_data')


            # Build parameters
            if action == 'upload':
                connect_kwargs = {
                    'hostname'    : self.config['FILETRANSFER']['HOST'],
                    'username'    : self.config['FILETRANSFER']['USERNAME'],
                    'password'    : self.config['FILETRANSFER']['PASSWORD'],
                    'private_key' : self.config['FILETRANSFER'].get('PRIVATE_KEY'),
                    'public_key'  : self.config['FILETRANSFER'].get('PUBLIC_KEY'),
                    'cert_bypass' : self.config['FILETRANSFER'].get('CERT_BYPASS', True),
                }

                put_kwargs = {
                    'local_file'  : Path(local_file),
                    'remote_file' : Path(remote_file),
                }

                try:
                    client_class = getattr(filetransfer, self.config['FILETRANSFER']['CLASSNAME'])
                except AttributeError:
                    logger.error('Unknown filetransfer class: %s', self.config['FILETRANSFER']['CLASSNAME'])
                    task.setFailed('Unknown filetransfer class: {0:s}'.format(self.config['FILETRANSFER']['CLASSNAME']))
                    return

                client = client_class(self.config)
                client.timeout = self.config['FILETRANSFER']['TIMEOUT']

                if self.config['FILETRANSFER']['PORT']:
                    client.port = self.config['FILETRANSFER']['PORT']

            elif action == 'mqttpub':
                connect_kwargs = {
                    'transport'   : self.config['MQTTPUBLISH']['TRANSPORT'],
                    'hostname'    : self.config['MQTTPUBLISH']['HOST'],
                    'username'    : self.config['MQTTPUBLISH']['USERNAME'],
                    'password'    : self.config['MQTTPUBLISH']['PASSWORD'],
                    'tls'         : self.config['MQTTPUBLISH']['TLS'],
                    'cert_bypass' : self.config['MQTTPUBLISH'].get('CERT_BYPASS', True),
                }

                put_kwargs = {
                    'local_file'  : Path(local_file),
                    'base_topic'  : self.config['MQTTPUBLISH']['BASE_TOPIC'],
                    'qos'         : self.config['MQTTPUBLISH']['QOS'],
                    'mq_data'     : mq_data,
                }

                try:
                    client_class = getattr(filetransfer, 'paho_mqtt')
                except AttributeError:
                    logger.error('Unknown filetransfer class: %s', 'paho_mqtt')
                    task.setFailed('Unknown filetransfer class: {0:s}'.format('paho_mqtt'))
                    return

                client = client_class(self.config)

                if self.config['MQTTPUBLISH']['PORT']:
                    client.port = self.config['MQTTPUBLISH']['PORT']

            else:
                task.setFailed('Invalid transfer action')
                raise Exception('Invalid transfer action')


            start = time.time()

            try:
                client.connect(**connect_kwargs)
            except filetransfer.exceptions.ConnectionFailure as e:
                logger.error('Connection failure: %s', e)
                client.close()
                task.setFailed('Connection failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'connection',
                    'File transfer connection failure: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                task.setFailed('Authentication failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'authentication',
                    'File transfer authentication failure: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.CertificateValidationFailure as e:
                logger.error('Certificate validation failure: %s', e)
                client.close()
                task.setFailed('Certificate validation failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'certificate',
                    'File transfer certificate validation failed: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue

            # Upload file
            try:
                client.put(**put_kwargs)
            except filetransfer.exceptions.ConnectionFailure as e:
                logger.error('Connection failure: %s', e)
                client.close()
                task.setFailed('Connection failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'connection',
                    'File transfer connection failure: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                task.setFailed('Authentication failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'authentication',
                    'File transfer authentication failure: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.CertificateValidationFailure as e:
                logger.error('Certificate validation failure: %s', e)
                client.close()
                task.setFailed('Certificate validation failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'certificate',
                    'File transfer certificate validation failed: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.TransferFailure as e:
                logger.error('Tranfer failure: %s', e)
                client.close()
                task.setFailed('Tranfer failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'filetransfer',
                    'File transfer failed: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue
            except filetransfer.exceptions.PermissionFailure as e:
                logger.error('Permission failure: %s', e)
                client.close()
                task.setFailed('Permission failure')

                self._miscDb.addNotification(
                    NotificationCategory.UPLOAD,
                    'permission',
                    'File transfer permission failure: {0:s}'.format(str(e)),
                    expire=timedelta(hours=1),
                )

                continue


            # close file transfer client
            client.close()

            upload_elapsed_s = time.time() - start
            logger.info('Upload transaction completed in %0.4f s', upload_elapsed_s)


            task.setSuccess('File uploaded')


            if remove_local:
                local_file_p = Path(local_file)

                try:
                    local_file_p.unlink()
                except PermissionError as e:
                    logger.error('Cannot remove local file: %s', str(e))
                    return
                except FileNotFoundError as e:
                    logger.error('Cannot remove local file: %s', str(e))
                    return


            #raise Exception('Testing uncaught exception')

