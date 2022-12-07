import time
from pathlib import Path
import traceback
import logging

from multiprocessing import Process
#from threading import Thread
import queue

#from .flask import db

from .flask.models import TaskQueueState
from .flask.models import TaskQueueQueue
from .flask.models import IndiAllSkyDbTaskQueueTable

from . import filetransfer

from sqlalchemy.orm.exc import NoResultFound

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
        self.error_q = error_q
        self.upload_q = upload_q


    def run(self):
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
            time.sleep(0.7)  # sleep every loop

            try:
                u_dict = self.upload_q.get_nowait()
            except queue.Empty:
                continue


            if u_dict.get('stop'):
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
                return
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                task.setFailed('Authentication failure')
                return
            except filetransfer.exceptions.CertificateValidationFailure as e:
                logger.error('Certificate validation failure: %s', e)
                client.close()
                task.setFailed('Certificate validation failure')
                return

            # Upload file
            try:
                client.put(**put_kwargs)
            except filetransfer.exceptions.ConnectionFailure as e:
                logger.error('Connection failure: %s', e)
                client.close()
                task.setFailed('Connection failure')
                return
            except filetransfer.exceptions.AuthenticationFailure as e:
                logger.error('Authentication failure: %s', e)
                client.close()
                task.setFailed('Authentication failure')
                return
            except filetransfer.exceptions.TransferFailure as e:
                logger.error('Tranfer failure: %s', e)
                client.close()
                task.setFailed('Tranfer failure')
                return
            except filetransfer.exceptions.PermissionFailure as e:
                logger.error('Permission failure: %s', e)
                client.close()
                task.setFailed('Permission failure')
                return
            except filetransfer.exceptions.CertificateValidationFailure as e:
                logger.error('Certificate validation failure: %s', e)
                client.close()
                task.setFailed('Certificate validation failure')
                return


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

