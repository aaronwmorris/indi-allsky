from .generic import GenericFileTransfer
from .exceptions import AuthenticationFailure
from .exceptions import ConnectionFailure
from .exceptions import TransferFailure

from pathlib import Path
import ssl
import io
import socket
import time
import logging

logger = logging.getLogger('indi_allsky')


class paho_mqtt(GenericFileTransfer):
    def __init__(self, *args, **kwargs):
        super(paho_mqtt, self).__init__(*args, **kwargs)

        self._port = 1883

        self.mq_transport = None
        self.mq_hostname = None
        self.mq_auth = None
        self.mq_tls = None


    def connect(self, *args, **kwargs):
        super(paho_mqtt, self).connect(*args, **kwargs)

        transport = kwargs['transport']
        hostname = kwargs['hostname']
        username = kwargs['username']
        password = kwargs.get('password') if kwargs.get('password') else None
        tls = kwargs.get('tls')
        cert_bypass = kwargs.get('cert_bypass')


        self.mq_transport = transport
        self.mq_hostname = hostname

        if tls:
            self.mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
                'insecure'    : False,
            }

            if cert_bypass:
                self.mq_tls['cert_reqs'] = ssl.CERT_NONE
                self.mq_tls['insecure'] = True



        if username:
            self.mq_auth = {
                'username' : username,
                'password' : password,
            }


    def close(self):
        super(paho_mqtt, self).close()


    def put(self, *args, **kwargs):
        super(paho_mqtt, self).put(*args, **kwargs)

        import paho.mqtt.publish as publish
        from paho.mqtt import MQTTException


        local_file = kwargs['local_file']
        base_topic = kwargs['base_topic']
        qos        = kwargs['qos']
        mq_data    = kwargs['mq_data']
        image_topic = kwargs['image_topic']
        publish_image = kwargs['publish_image']

        local_file_p = Path(local_file)


        message_list = list()

        # publish image
        if publish_image:
            with io.open(local_file_p, 'rb') as f_localfile:
                message_list.append({
                    'topic'    : '/'.join((base_topic, image_topic)),
                    'payload'  : f_localfile.read(),  # this requires paho-mqtt >= v2.0.0
                    'qos'      : qos,
                    'retain'   : True,
                })


        for k, v in mq_data.items():
            message_list.append({
                'topic'    : '/'.join((base_topic, k)),
                'payload'  : v,
                'qos'      : qos,
                'retain'   : True,
            })


        start = time.time()

        try:
            publish.multiple(
                message_list,
                transport=self.mq_transport,
                hostname=self.mq_hostname,
                port=self._port,
                client_id='',
                keepalive=60,
                auth=self.mq_auth,
                tls=self.mq_tls,
            )
        except socket.gaierror as e:
            raise ConnectionFailure(str(e)) from e
        except socket.timeout as e:
            raise ConnectionFailure(str(e)) from e
        except ssl.SSLCertVerificationError as e:
            raise ConnectionFailure(str(e)) from e
        except ConnectionRefusedError as e:
            raise ConnectionFailure(str(e)) from e
        except MQTTException as e:
            raise AuthenticationFailure(str(e)) from e
        except ValueError as e:
            # this can happen if msgs is empty
            raise TransferFailure(str(e)) from e

        upload_elapsed_s = time.time() - start
        local_file_size = local_file_p.stat().st_size
        logger.info('File transferred in %0.4f s (%0.2f kB/s)', upload_elapsed_s, local_file_size / upload_elapsed_s / 1024)


