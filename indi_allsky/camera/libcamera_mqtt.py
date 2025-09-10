import time
from pathlib import Path
import tempfile
import json
import logging

from .libcamera import IndiClientLibCameraGeneric

from ..exceptions import BinModeException


logger = logging.getLogger('indi_allsky')


class IndiClientLibCameraMqttGeneric(IndiClientLibCameraGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraMqttGeneric, self).__init__(*args, **kwargs)
        import ssl
        import paho.mqtt.client as mqtt


        # modified in MQTT methods
        self.user_data = {
            'waiting_on_exposure': False
        }


        host = self.config.get('CAMERA', {}).get('MQTT_HOST', 'localhost')
        port = self.config.get('CAMERA', {}).get('MQTT_PORT', 8883)
        username = self.config.get('CAMERA', {}).get('MQTT_USERNAME', 'indi-allsky')
        password = self.config.get('CAMERA', {}).get('MQTT_PASSWORD', '')
        tls = self.config.get('CAMERA', {}).get('MQTT_TLS', True)
        cert_bypass = self.config.get('CAMERA', {}).get('MQTT_CERT_BYPASS', True)

        self._qos = self.config.get('CAMERA', {}).get('MQTT_QOS', 0)


        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )


        if username:
            self.client.username_pw_set(username=username, password=password)


        if tls:
            mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
            }

            if cert_bypass:
                mq_tls['cert_reqs'] = ssl.CERT_NONE

            self.client.tls_set(**mq_tls)


        self.client.connect(
            host,
            port=port,
        )


        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe


        self.client.user_data_set(self.user_data)

        self.client.loop_start()


    def setCcdExposure(self, exposure, sync=False, timeout=None):
        import paho.mqtt.properties as mqtt_props
        from paho.mqtt.packettypes import PacketTypes


        if self.active_exposure:
            return


        libcamera_camera_id = self.config.get('LIBCAMERA', {}).get('CAMERA_ID', 0)


        if self.night_v.value:
            # night
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE', 'jpg')
        else:
            # day
            image_type = self.config.get('LIBCAMERA', {}).get('IMAGE_FILE_TYPE_DAY', 'jpg')


        try:
            image_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.{0:s}'.format(image_type), delete=True)
            image_tmp_f.close()
            image_tmp_p = Path(image_tmp_f.name)

            metadata_tmp_f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=True)
            metadata_tmp_f.close()
            metadata_tmp_p = Path(metadata_tmp_f.name)
        except OSError as e:
            logger.error('OSError: %s', str(e))
            return


        try:
            binmode_option = self._getBinModeOptions(self.bin_v.value)
        except BinModeException as e:
            logger.error('Invalid setting: %s', str(e))
            binmode_option = ''


        self.current_exposure_file_p = image_tmp_p
        self.current_metadata_file_p = metadata_tmp_p


        self._exposure = exposure

        exposure_us = int(exposure * 1000000)

        if image_type in ['dng']:
            cmd = [
                '--nopreview',
                '--camera', '{0:d}'.format(libcamera_camera_id),
                '--raw',
                '--denoise', 'off',
                '--gain', '{0:d}'.format(self.gain_v.value),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', str(metadata_tmp_p),
                '--metadata-format', 'json',
            ]
        elif image_type in ['jpg', 'png']:
            #logger.warning('RAW frame mode disabled due to low memory resources')
            cmd = [
                '--nopreview',
                '--camera', '{0:d}'.format(libcamera_camera_id),
                '--encoding', '{0:s}'.format(image_type),
                '--quality', '95',
                '--gain', '{0:d}'.format(self.gain_v.value),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', str(metadata_tmp_p),
                '--metadata-format', 'json',
            ]
        else:
            raise Exception('Invalid image type')



        if self.night_v.value:
            #  night

            if self.config.get('LIBCAMERA', {}).get('IMMEDIATE', True):
                cmd.insert(1, '--immediate')

            # Auto white balance, AWB causes long exposure times at night
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE'):
                awb = self.config.get('LIBCAMERA', {}).get('AWB', 'auto')
                cmd.extend(['--awb', awb])
            else:
                # awb enabled by default, the following disables
                cmd.extend(['--awbgains', '1,1'])


        else:
            # daytime

            if self.config.get('LIBCAMERA', {}).get('IMMEDIATE_DAY', True):
                cmd.insert(1, '--immediate')

            # Auto white balance, AWB causes long exposure times at night
            if self.config.get('LIBCAMERA', {}).get('AWB_ENABLE_DAY'):
                awb = self.config.get('LIBCAMERA', {}).get('AWB_DAY', 'auto')
                cmd.extend(['--awb', awb])
            else:
                # awb enabled by default, the following disables
                cmd.extend(['--awbgains', '1,1'])


        # add --mode flags for binning
        if binmode_option:
            cmd.extend(binmode_option.split(' '))


        # extra options get added last
        if self.night_v.value:
            #  night
            # Add extra config options
            extra_options = self.config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS')
            if extra_options:
                cmd.extend(extra_options.split(' '))

        else:
            # daytime

            # Add extra config options
            extra_options = self.config.get('LIBCAMERA', {}).get('EXTRA_OPTIONS_DAY')
            if extra_options:
                cmd.extend(extra_options.split(' '))


        # Finally add output file
        cmd.extend(['--output', str(image_tmp_p)])


        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.active_exposure = True
        self.user_data['waiting_on_exposure'] = True


        user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
        user_properties.UserProperty = [
            ("Content-Type", "application/json"),
        ]


        payload = {
            'action'   : 'exposure',
            'cmd_args' : cmd,
        }

        self.client.publish(self.exposure_topic, payload=json.dumps(payload), qos=self.qos, retain=False, properties=user_properties)


        if sync:
            pass
            #    raise TimeOutException('Timeout waiting for exposure')


            self.active_exposure = False
            self.user_data['waiting_on_exposure'] = False

            self._processMetadata()

            self._queueImage()


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if not self.user_data['waiting_on_exposure']:
            return False, 'BUSY'


        if self.active_exposure:
            # if we get here, that means the camera is finished with the exposure
            self.active_exposure = False


            self._processMetadata()

            self._queueImage()


        return True, 'READY'


    def abortCcdExposure(self):
        import paho.mqtt.properties as mqtt_props
        from paho.mqtt.packettypes import PacketTypes

        logger.warning('Aborting exposure')

        self.active_exposure = False
        self.user_data['waiting_on_exposure'] = False


        user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
        user_properties.UserProperty = [
            ("Content-Type", "application/json"),
        ]


        payload = {
            'action' : 'abort',
        }

        self.client.publish(self.exposure_topic, payload=json.dumps(payload), qos=self.qos, retain=False, properties=user_properties)


    def on_message(self, client, userdata, message):
        message.payload
        message.properties


        #userdata['waiting_on_exposure'] = False


    def on_publish(self, client, userdata, mid, reason_code, properties):
        #logger.info('MQTT message published')
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


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            # we should always subscribe from on_connect callback to be sure
            # our subscribed is persisted across reconnections.
            for topic in self.topic_list:
                logger.info('Subscribing to topic %s', topic)
                client.subscribe(topic)



