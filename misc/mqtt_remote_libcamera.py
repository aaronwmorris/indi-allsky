#!/usr/bin/env python3


### Requirements
#paho-mqtt >= 2.0.0


### MQTT settings
MQTT_HOSTNAME = 'localhost'
MQTT_PORT = 8883
MQTT_USERNAME = 'username'
MQTT_PASSWORD = 'password123'
MQTT_TLS = True
MQTT_CERT_BYPASS = True

MQTT_EXPOSURE_TOPIC = 'libcamera_exposure'
MQTT_METADATA_TOPIC = 'libcamera_metadata'
MQTT_IMAGE_TOPIC = 'libcamera_image'


import sys
import time
#import json
import ssl
import paho.mqtt.client as mqtt
import signal
import logging


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)

LOG_FORMATTER_STREAM = logging.Formatter('%(asctime)s [%(levelname)s] %(processName)s %(funcName)s() [%(lineno)d]: %(message)s')
LOG_HANDLER_STREAM = logging.StreamHandler()
LOG_HANDLER_STREAM.setFormatter(LOG_FORMATTER_STREAM)
logger.addHandler(LOG_HANDLER_STREAM)


class MqttRemoteLibcamera(object):

    def __init__(self):
        self.client = None

        self.active_exposure = False
        self.exposure_start_time = None

        self._shutdown = False


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')
        self._shutdown = True


    def run(self):
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )


        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        #self.client.on_unsubscribe = self.on_unsubscribe


        if MQTT_USERNAME:
            self.client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)


        if MQTT_TLS:
            mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
            }

            if MQTT_CERT_BYPASS:
                mq_tls['cert_reqs'] = ssl.CERT_NONE

            self.client.tls_set(**mq_tls)


        try:
            self.client.connect(MQTT_HOSTNAME, port=MQTT_PORT)
        except ConnectionRefusedError as e:
            logger.error('MQTT ConnectionRefusedError: %s', str(e))

            self.dew_heater.deinit()
            self.fan.deinit()

            sys.exit(1)


        signal.signal(signal.SIGINT, self.sigint_handler)
        signal.signal(signal.SIGTERM, self.sigint_handler)


        self.client.loop_start()


        while True:
            time.sleep(1.0)

            if self._shutdown:
                break


        ### Shutdown
        self.client.disconnect()
        self.client.loop_stop()


    def on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        # only report a single channel
        if reason_code_list[0].is_failure:
            logger.error('Broker rejected you subscription: %s', reason_code_list[0])
        else:
            logger.info('Broker granted the following QoS: %d', reason_code_list[0].value)


    def on_unsubscribe(self, client, userdata, mid, reason_code_list, properties):
        # Be careful, the reason_code_list is only present in MQTTv5.
        # In MQTTv3 it will always be empty
        if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
            logger.info('unsubscribe succeeded')
        else:
            logger.error('Broker replied with failure: %s', reason_code_list[0])

        client.disconnect()


    def on_message(self, client, userdata, message):
        pass


    def on_publish(self, client, userdata, mid, reason_code, properties):
        #logger.info('MQTT message published')
        pass


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            # we should always subscribe from on_connect callback to be sure
            # our subscribed is persisted across reconnections.
            logger.info('Subscribing to topic %s', MQTT_EXPOSURE_TOPIC)
            client.subscribe(MQTT_EXPOSURE_TOPIC)


if __name__ == "__main__":
    MqttRemoteLibcamera().run()
