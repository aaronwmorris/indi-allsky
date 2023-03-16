import time
from datetime import timedelta
from pathlib import Path
import signal
import traceback
import logging

from multiprocessing import Process
#from threading import Thread
import queue

from . import constants

from .flask import create_app
from .flask import db
from .flask.miscDb import miscDb

from .flask import models

from . import filetransfer

from sqlalchemy.orm.exc import NoResultFound

from .exceptions import TimeOutException


app = create_app()

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


        if self.config.get('IMAGE_FOLDER'):
            self.image_dir = Path(self.config['IMAGE_FOLDER']).absolute()
        else:
            self.image_dir = Path(__file__).parent.parent.joinpath('html', 'images').absolute()



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


            # new context for every task, reduces the effects of caching
            with app.app_context():
                self.processUpload(u_dict)


    def processUpload(self, u_dict):
        task_id = u_dict['task_id']


        try:
            task = models.IndiAllSkyDbTaskQueueTable.query\
                .filter(models.IndiAllSkyDbTaskQueueTable.id == task_id)\
                .filter(models.IndiAllSkyDbTaskQueueTable.state == models.TaskQueueState.QUEUED)\
                .filter(models.IndiAllSkyDbTaskQueueTable.queue == models.TaskQueueQueue.UPLOAD)\
                .one()

        except NoResultFound:
            logger.error('Task ID %d not found', task_id)
            return


        task.setRunning()


        action = task.data['action']

        local_file = task.data.get('local_file')

        entry_model = task.data.get('model')
        entry_id = task.data.get('id')

        remote_file = task.data.get('remote_file')
        remove_local = task.data.get('remove_local')

        asset_type = task.data.get('asset_type')

        metadata = task.data.get('metadata')


        if entry_model and entry_id:
            # lookup filename in model

            try:
                _model = getattr(models, entry_model)
            except AttributeError:
                logger.error('Model not found: %s', entry_model)
                task.setFailed('Model not found: {0:s}'.format(entry_model))
                return

            try:
                entry = _model.query\
                    .filter(_model.id == entry_id)\
                    .one()
            except NoResultFound:
                logger.error('ID %d not found in %s', entry_id, entry_model)
                task.setFailed('ID {0:d} not found in {1:s}'.format(entry_id, entry_model))
                return

            local_file_p = Path(entry.filename)


        elif local_file:
            # use given file name
            local_file_p = Path(local_file)
            entry = None
        else:
            logger.error('Entry model or filename not defined')
            task.setFailed('Entry model or filename not defined')
            return


        # Build parameters
        if action == constants.TRANSFER_UPLOAD:
            connect_kwargs = {
                'hostname'    : self.config['FILETRANSFER']['HOST'],
                'username'    : self.config['FILETRANSFER']['USERNAME'],
                'password'    : self.config['FILETRANSFER']['PASSWORD'],
                'private_key' : self.config['FILETRANSFER'].get('PRIVATE_KEY'),
                'public_key'  : self.config['FILETRANSFER'].get('PUBLIC_KEY'),
                'cert_bypass' : self.config['FILETRANSFER'].get('CERT_BYPASS', True),
            }

            put_kwargs = {
                'local_file'  : local_file_p,
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

        elif action == constants.TRANSFER_S3:
            s3_key = local_file_p.relative_to(self.image_dir)

            if asset_type == constants.ASSET_IMAGE:
                if self.config['S3UPLOAD']['EXPIRE_IMAGES']:
                    expire_days = self.config['IMAGE_EXPIRE_DAYS']
                else:
                    expire_days = None
            else:
                # assume timelapse asset (video, keogram, startrail, etc)
                if self.config['S3UPLOAD']['EXPIRE_TIMELAPSE']:
                    expire_days = self.config['TIMELAPSE_EXPIRE_DAYS']
                else:
                    expire_days = None


            connect_kwargs = {
                'username'     : '*',  # not logging access key
                'access_key'   : self.config['S3UPLOAD']['ACCESS_KEY'],
                'secret_key'   : self.config['S3UPLOAD']['SECRET_KEY'],
                'region'       : self.config['S3UPLOAD']['REGION'],
                'hostname'     : self.config['S3UPLOAD']['HOST'],  # endpoint_url
                'tls'          : self.config['S3UPLOAD']['TLS'],
                'cert_bypass'  : self.config['S3UPLOAD']['CERT_BYPASS'],
            }

            put_kwargs = {
                'local_file'    : local_file_p,
                'bucket'        : self.config['S3UPLOAD']['BUCKET'],
                'key'           : str(s3_key),
                'storage_class' : self.config['S3UPLOAD']['STORAGE_CLASS'],
                'expire_days'   : expire_days,
                'acl'           : self.config['S3UPLOAD']['ACL'],
            }

            try:
                client_class = getattr(filetransfer, self.config['S3UPLOAD']['CLASSNAME'])
            except AttributeError:
                logger.error('Unknown filetransfer class: %s', self.config['S3UPLOAD']['CLASSNAME'])
                task.setFailed('Unknown filetransfer class: {0:s}'.format(self.config['S3UPLOAD']['CLASSNAME']))
                return


            client = client_class(self.config)
            client.timeout = self.config['FILETRANSFER']['TIMEOUT']  # reusing file transfer timeout


            if self.config['S3UPLOAD']['PORT']:
                client.port = self.config['S3UPLOAD']['PORT']


        elif action == constants.TRANSFER_MQTT:
            connect_kwargs = {
                'transport'   : self.config['MQTTPUBLISH']['TRANSPORT'],
                'hostname'    : self.config['MQTTPUBLISH']['HOST'],
                'username'    : self.config['MQTTPUBLISH']['USERNAME'],
                'password'    : self.config['MQTTPUBLISH']['PASSWORD'],
                'tls'         : self.config['MQTTPUBLISH']['TLS'],
                'cert_bypass' : self.config['MQTTPUBLISH'].get('CERT_BYPASS', True),
            }

            put_kwargs = {
                'local_file'  : local_file_p,
                'base_topic'  : self.config['MQTTPUBLISH']['BASE_TOPIC'],
                'qos'         : self.config['MQTTPUBLISH']['QOS'],
                'mq_data'     : metadata,
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

        elif action == constants.TRANSFER_SYNC_V1:
            ENDPOINT_URI = constants.ENDPOINT_V1[metadata['type']]

            connect_kwargs = {
                'hostname'     : '{0:s}/{1:s}'.format(self.config['SYNCAPI']['BASEURL'], ENDPOINT_URI),
                'username'     : self.config['SYNCAPI']['USERNAME'],
                'apikey'       : self.config['SYNCAPI']['APIKEY'],
                'cert_bypass'  : self.config['SYNCAPI']['CERT_BYPASS'],
            }

            put_kwargs = {
                'metadata'      : metadata,
                'local_file'    : local_file_p,
            }

            try:
                client_class = getattr(filetransfer, 'requests_syncapi_v1')
            except AttributeError:
                logger.error('Unknown filetransfer class: %s', 'requests_syncapi_v1')
                task.setFailed('Unknown filetransfer class: {0:s}'.format('requests_syncapi_v1'))
                return

            client = client_class(self.config)
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
                models.NotificationCategory.UPLOAD,
                'connection',
                '{0:s} file transfer connection failure: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.AuthenticationFailure as e:
            logger.error('Authentication failure: %s', e)
            client.close()
            task.setFailed('Authentication failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'authentication',
                '{0:s} file transfer authentication failure: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.CertificateValidationFailure as e:
            logger.error('Certificate validation failure: %s', e)
            client.close()
            task.setFailed('Certificate validation failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'certificate',
                '{0:s} file transfer certificate validation failed: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return

        # Upload file
        try:
            response = client.put(**put_kwargs)
        except filetransfer.exceptions.ConnectionFailure as e:
            logger.error('Connection failure: %s', e)
            client.close()
            task.setFailed('Connection failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'connection',
                '{0:s} file transfer connection failure: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.AuthenticationFailure as e:
            logger.error('Authentication failure: %s', e)
            client.close()
            task.setFailed('Authentication failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'authentication',
                '{0:s} file transfer authentication failure: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.CertificateValidationFailure as e:
            logger.error('Certificate validation failure: %s', e)
            client.close()
            task.setFailed('Certificate validation failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'certificate',
                '{0:s} file transfer certificate validation failed: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.TransferFailure as e:
            logger.error('Tranfer failure: %s', e)
            client.close()
            task.setFailed('Tranfer failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'filetransfer',
                '{0:s} file transfer failed: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return
        except filetransfer.exceptions.PermissionFailure as e:
            logger.error('Permission failure: %s', e)
            client.close()
            task.setFailed('Permission failure')

            self._miscDb.addNotification(
                models.NotificationCategory.UPLOAD,
                'permission',
                '{0:s} file transfer permission failure: {1:s}'.format(client_class.__name__, str(e)),
                expire=timedelta(hours=1),
            )

            return


        # close file transfer client
        client.close()

        upload_elapsed_s = time.time() - start
        logger.info('Upload transaction completed in %0.4f s', upload_elapsed_s)


        task.setSuccess('File uploaded')


        if entry and action == constants.TRANSFER_UPLOAD:
            entry.uploaded = True
            db.session.commit()


        if entry and action == constants.TRANSFER_S3:
            entry.s3_key = str(s3_key)
            db.session.commit()

            # perform syncapi after s3 (if enabled)
            metadata['s3_key'] = str(s3_key)
            self._syncapi(entry, metadata)


        if entry and action == constants.TRANSFER_SYNC_V1:
            entry.sync_id = response['id']
            db.session.commit()


        if remove_local:
            try:
                local_file_p.unlink()
            except PermissionError as e:
                logger.error('Cannot remove local file: %s', str(e))
                return
            except FileNotFoundError as e:
                logger.error('Cannot remove local file: %s', str(e))
                return


        #raise Exception('Testing uncaught exception')


    def _syncapi(self, asset_entry, metadata):
        ### sync camera
        if not self.config.get('SYNCAPI', {}).get('ENABLE'):
            return

        if not self.config.get('SYNCAPI', {}).get('POST_S3'):
            # file is *NOT* uploaded after s3 upload
            return

        if not asset_entry:
            #logger.warning('S3 uploading disabled')
            return

        # tell worker to upload file
        jobdata = {
            'action'      : constants.TRANSFER_SYNC_V1,
            'model'       : asset_entry.__class__.__name__,
            'id'          : asset_entry.id,
            'metadata'    : metadata,
        }

        upload_task = models.IndiAllSkyDbTaskQueueTable(
            queue=models.TaskQueueQueue.UPLOAD,
            state=models.TaskQueueState.QUEUED,
            data=jobdata,
        )
        db.session.add(upload_task)
        db.session.commit()

        self.upload_q.put({'task_id' : upload_task.id})

