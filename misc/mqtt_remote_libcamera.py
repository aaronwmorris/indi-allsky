#!/usr/bin/env python3


### Requirements
#paho-mqtt >= 2.0.0


import os

### MQTT settings
MQTT_HOSTNAME = os.environ.get('MQTT_HOSTNAME', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', 8883))
MQTT_USERNAME = os.environ.get('MQTT_USERNAME', 'username')
MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD', 'password123')
MQTT_TLS = int(os.environ.get('MQTT_TLS', 1))
MQTT_CERT_BYPASS = int(os.environ.get('MQTT_CERT_BYPASS', 1))

MQTT_EXPOSURE_TOPIC = os.environ.get('MQTT_EXPOSURE_TOPIC', 'libcamera_exposure')
MQTT_METADATA_TOPIC = os.environ.get('MQTT_METADATA_TOPIC', 'libcamera_metadata')
MQTT_IMAGE_TOPIC = os.environ.get('MQTT_IMAGE_TOPIC', 'libcamera_image')


import sys
import io
import time
from pathlib import Path
import json
import queue
import subprocess
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

        self.libcamera_process = None

        self.active_exposure = False
        self.exposure_start_time = None

        self.current_exposure_file_p = None
        self.current_metadata_file_p = None

        self.user_data = {
            'queue' : queue.Queue(),
        }

        self._shutdown = False


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')
        self._shutdown = True


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')
        self._shutdown = True


    def run(self):
        logger.info('MQTT Hostname: %s', MQTT_HOSTNAME)
        logger.info('MQTT Port:     %d', MQTT_PORT)
        logger.info('MQTT Username: %s', MQTT_USERNAME)
        logger.info('MQTT TLS:      %s', str(bool(MQTT_TLS)))
        logger.info('Exposure Topic:  %s', MQTT_EXPOSURE_TOPIC)
        logger.info('Image Topic:     %s', MQTT_IMAGE_TOPIC)
        logger.info('Metadata  Topic: %s', MQTT_METADATA_TOPIC)
        time.sleep(3.0)


        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )


        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        #self.client.on_unsubscribe = self.on_unsubscribe

        self.client.user_data_set(self.user_data)


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


        ### Main program loop
        while True:
            time.sleep(0.1)


            if self._shutdown:
                break


            try:
                exposure_data = self.user_data['queue'].get_nowait()
                #logger.info('Exposure data: %s', str(exposure_data))


                try:
                    action_str = exposure_data['action']
                    method_action = getattr(self, action_str)
                    method_action(**exposure_data['kwargs'])
                except AttributeError:
                    logger.error('Unknown method: %s', action_str)
                    continue
                except KeyError:
                    logger.error('Malformed exposure request')
                    continue

            except queue.Empty:
                pass


            self.getCcdExposureStatus()


        ### Shutdown
        self.client.disconnect()
        self.client.loop_stop()


    def setCcdExposure(self, **kwargs):
        cmd = kwargs['cmd']
        files = kwargs['files']


        self.current_exposure_file_p = Path(files['images'])
        self.current_metadata_file_p = Path(files['metadata'])


        logger.info('image command: %s', ' '.join(cmd))


        self.exposure_start_time = time.time()

        self.libcamera_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        self.active_exposure = True


    def getCcdExposureStatus(self):
        import paho.mqtt.properties as mqtt_props
        from paho.mqtt.packettypes import PacketTypes


        # returns camera_ready, exposure_state
        if self._libCameraProcessRunning():
            return


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False


            if self.libcamera_process.returncode != 0:
                # log errors
                stdout = self.libcamera_process.stdout
                for line in stdout.readlines():
                    logger.error('rpicam-still error: %s', line)

                # not returning, just log the error


            if not self.current_exposure_file_p.exists() or not self.current_metadata_file_p.exists():
                logger.error('Image or metadata file does not exist, cancelling...')

                try:
                    self.current_exposure_file_p.unlink()
                except FileNotFoundError:
                    pass


                try:
                    self.current_metadata_file_p.unlink()
                except FileNotFoundError:
                    pass


                return


            exposure_elapsed_s = time.time() - self.exposure_start_time
            logger.info('Exposure completed in %0.4f s', exposure_elapsed_s)


            metadata_user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
            metadata_user_properties.UserProperty = [
                ("Content-Type", "application/json"),
            ]


            with io.open(str(self.current_metadata_file_p), 'rb') as f_metadata:
                payload = json.load(f_metadata.read())

                self.client.publish(
                    self.metadata_topic,
                    payload=json.dumps(payload),
                    qos=self.qos,
                    retain=False,
                    properties=metadata_user_properties,
                )


            image_user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
            image_user_properties.UserProperty = [
                ("Content-Type", "application/octet-stream"),
            ]


            with io.open(str(self.current_exposure_file_p), 'rb') as f_image:
                self.client.publish(
                    self.image_topic,
                    payload=f_image.read(),  # this requires paho-mqtt >= v2.0.0
                    qos=self.qos,
                    retain=False,
                    properties=metadata_user_properties,
                )


            self.current_exposure_file_p.unlink()
            self.current_metadata_file_p.unlink()


    def _libCameraProcessRunning(self):
        if not self.libcamera_process:
            return False

        # poll returns None when process is active, rc (normally 0) when finished
        poll = self.libcamera_process.poll()
        if isinstance(poll, type(None)):
            return True

        return False


    def abortCcdExposure(self, **kwargs):
        if not self._libCameraProcessRunning():
            return


        logger.warning('Aborting exposure')

        self.active_exposure = False

        for _ in range(5):
            if not self._libCameraProcessRunning():
                break

            self.libcamera_process.terminate()
            time.sleep(0.5)
            continue


        if self._libCameraProcessRunning():
            self.libcamera_process.kill()
            self.libcamera_process.poll()  # close out the process


        try:
            if self.current_exposure_file_p:
                self.current_exposure_file_p.unlink()
        except FileNotFoundError:
            pass


        try:
            if self.current_metadata_file_p:
                self.current_metadata_file_p.unlink()
        except FileNotFoundError:
            pass


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
        logger.info('Recieved exposure message')

        try:
            exposure_data = json.loads(message.payload)
        except ValueError as e:
            logger.error('MQTT JSON data error: %s', str(e))
            return


        userdata['queue'].put(exposure_data)


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
