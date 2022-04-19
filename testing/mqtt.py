#!/usr/bin/env python3

import argparse
import logging
import json
import time
import paho.mqtt.publish as publish
import ssl
#from pprint import pformat


logging.basicConfig(level=logging.INFO)
logger = logging



class MqttTest(object):
    def __init__(self, f_config):
        self.config = json.loads(f_config.read())

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
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--config',
        '-c',
        help='config file',
        type=argparse.FileType('r'),
        default='/etc/indi-allsky/config.json',
    )


    args = argparser.parse_args()

    mt = MqttTest(args.config)
    mt.main()

