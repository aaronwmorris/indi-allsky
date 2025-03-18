#!/usr/bin/env python3

import sys
import logging
import time
import paho.mqtt.publish as publish
import ssl
from pathlib import Path
#from pprint import pformat

from sqlalchemy.orm.exc import NoResultFound

sys.path.append(str(Path(__file__).parent.absolute().parent))


from indi_allsky.flask import create_app
from indi_allsky.config import IndiAllSkyConfig

# setup flask context for db access
app = create_app()
app.app_context().push()


logger = logging.getLogger('indi_allsky')

LOG_FORMATTER_STREAM = logging.Formatter('[%(levelname)s]: %(message)s')

LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)

logger.handlers.clear()  # remove syslog
logger.addHandler(LOG_HANDLER_STREAM)




class MqttTest(object):
    def __init__(self):
        try:
            self._config_obj = IndiAllSkyConfig()
            #logger.info('Loaded config id: %d', self._config_obj.config_id)
        except NoResultFound:
            logger.error('No config file found, please import a config')
            sys.exit(1)

        self.config = self._config_obj.config


        self.tls = None
        self.mq_auth = None


    def main(self):
        if self.config['MQTTPUBLISH']['TLS']:
            self.mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
                'insecure'    : False,
            }

            if self.config['MQTTPUBLISH']['CERT_BYPASS']:
                self.mq_tls['cert_reqs'] = ssl.CERT_NONE
                self.mq_tls['insecure']  = True


        if self.config['MQTTPUBLISH']['USERNAME']:
            self.mq_auth = {
                'username' : self.config['MQTTPUBLISH']['USERNAME'],
                'password' : self.config['MQTTPUBLISH']['PASSWORD'],
            }

        message_list = list()
        message_list.append({
            'topic'    : '/'.join((self.config['MQTTPUBLISH']['BASE_TOPIC'], 'test')),
            'payload'  : int(time.time()),
            'qos'      : self.config['MQTTPUBLISH']['QOS'],
            'retain'   : True,
        })


        start = time.time()

        publish.multiple(
            message_list,
            transport=self.config['MQTTPUBLISH']['TRANSPORT'],
            hostname=self.config['MQTTPUBLISH']['HOST'],
            port=self.config['MQTTPUBLISH']['PORT'],
            client_id='',
            keepalive=60,
            auth=self.mq_auth,
            tls=self.mq_tls,
        )

        upload_elapsed_s = time.time() - start
        logger.info('Published in %0.4f', upload_elapsed_s)




if __name__ == "__main__":
    mt = MqttTest()
    mt.main()

