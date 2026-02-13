import time
from pathlib import Path
import io
import tempfile
import json
import logging

from .libcamera import IndiClientLibCameraGeneric

from .. import constants

from ..exceptions import BinModeException


logger = logging.getLogger('indi_allsky')


class IndiClientLibCameraMqttGeneric(IndiClientLibCameraGeneric):

    libcamera_exec = 'rpicam-still'


    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraMqttGeneric, self).__init__(*args, **kwargs)
        import ssl
        import paho.mqtt.client as mqtt


        # modified in MQTT methods
        self.user_data = {
            'waiting_on_image'    : False,
            'waiting_on_metadata' : False,
        }


        transport = self.config.get('LIBCAMERA', {}).get('MQTT_TRANSPORT', 'tcp')
        protocol_str = self.config.get('LIBCAMERA', {}).get('MQTT_PROTOCOL', 'MQTTv5')
        host = self.config.get('LIBCAMERA', {}).get('MQTT_HOST', 'localhost')
        port = self.config.get('LIBCAMERA', {}).get('MQTT_PORT', 8883)
        username = self.config.get('LIBCAMERA', {}).get('MQTT_USERNAME', 'indi-allsky')
        password = self.config.get('LIBCAMERA', {}).get('MQTT_PASSWORD', '')
        tls = self.config.get('LIBCAMERA', {}).get('MQTT_TLS', True)
        cert_bypass = self.config.get('LIBCAMERA', {}).get('MQTT_CERT_BYPASS', True)

        self._qos = self.config.get('LIBCAMERA', {}).get('QOS', 0)

        self.exposure_topic = self.config.get('LIBCAMERA', {}).get('MQTT_EXPOSURE_TOPIC', 'libcamera/exposure')
        self.image_topic = self.config.get('LIBCAMERA', {}).get('MQTT_IMAGE_TOPIC', 'libcamera/image')
        self.metadata_topic = self.config.get('LIBCAMERA', {}).get('MQTT_METADATA_TOPIC', 'libcamera/metadata')


        try:
            protocol = getattr(mqtt, protocol_str)
        except AttributeError:
            logger.error('Unknown MQTT Protocol: %s', protocol_str)
            raise


        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=protocol,
            transport=transport,
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


        # not catching ConnectionRefusedError
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


    @property
    def qos(self):
        return self._qos


    def disconnectServer(self, *args, **kwargs):
        super(IndiClientLibCameraMqttGeneric, self).disconnectServer(*args, **kwargs)

        self.client.disconnect()
        self.client.loop_stop()


    def setCcdExposure(self, exposure, gain, binning, sync=False, timeout=None, sqm_exposure=False):
        import paho.mqtt.properties as mqtt_props
        from paho.mqtt.packettypes import PacketTypes


        if self.active_exposure:
            return


        self.exposure = exposure
        self.sqm_exposure = sqm_exposure


        libcamera_camera_id = self.config.get('LIBCAMERA', {}).get('CAMERA_ID', 0)


        if self.night_av[constants.NIGHT_NIGHT]:
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
            binmode_option = self._getBinModeOptions(int(binning))
        except BinModeException as e:
            logger.error('Invalid setting: %s', str(e))
            binmode_option = ''


        self.current_exposure_file_p = image_tmp_p
        self.current_metadata_file_p = metadata_tmp_p


        if self.gain != float(round(gain, 2)):
            self.setCcdGain(gain)

        if self.binning != int(binning):
            self.setCcdBinning(binning)


        exposure_us = int(exposure * 1000000)

        if image_type in ['dng']:
            cmd = [
                self.libcamera_exec,
                '--nopreview',
                '--camera', '{0:d}'.format(libcamera_camera_id),
                '--raw',
                '--denoise', 'off',
                '--gain', '{0:0.2f}'.format(self.gain_av[constants.GAIN_CURRENT]),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', '{metadata:s}',
                '--metadata-format', 'json',
            ]
        elif image_type in ['jpg', 'png']:
            #logger.warning('RAW frame mode disabled due to low memory resources')
            cmd = [
                self.libcamera_exec,
                '--nopreview',
                '--camera', '{0:d}'.format(libcamera_camera_id),
                '--encoding', '{0:s}'.format(image_type),
                '--quality', '95',
                '--gain', '{0:0.2f}'.format(self.gain_av[constants.GAIN_CURRENT]),
                '--shutter', '{0:d}'.format(exposure_us),
                '--metadata', '{metadata:s}',
                '--metadata-format', 'json',
            ]
        else:
            raise Exception('Invalid image type')



        if self.night_av[constants.NIGHT_NIGHT]:
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


            # CCM
            if self.config.get('LIBCAMERA', {}).get('CCM_DISABLE'):
                cmd.extend(['--ccm', '1,1,1,1,1,1,1,1,1'])

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


            # CCM
            if self.config.get('LIBCAMERA', {}).get('CCM_DISABLE_DAY'):
                cmd.extend(['--ccm', '1,1,1,1,1,1,1,1,1'])


        # add --mode flags for binning
        if binmode_option:
            cmd.extend(binmode_option.split(' '))


        # extra options get added last
        if self.night_av[constants.NIGHT_NIGHT]:
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
        cmd.extend(['--output', '{image:s}'])


        logger.info('image command: %s', ' '.join(cmd))


        self.exposureStartTime = time.time()

        self.active_exposure = True
        self.user_data['waiting_on_image'] = True
        self.user_data['waiting_on_metadata'] = True


        user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
        user_properties.UserProperty = [
            ("Content-Type", "application/json"),
        ]


        payload = {
            'action'   : 'setCcdExposure',
            'kwargs'   : {
                'exposure'  : exposure,
                'gain'      : gain,
                'cmd'       : cmd,
                'files'     : {
                    'image' : image_tmp_p.name,  # file name is needed for the suffix
                },
            },
        }

        self.client.publish(self.exposure_topic, payload=json.dumps(payload), qos=self.qos, retain=False, properties=user_properties)


        # Update shared exposure value
        with self.exposure_av.get_lock():
            self.exposure_av[constants.EXPOSURE_CURRENT] = float(exposure)


        if sync:
            while self.user_data['waiting_on_metadata']:
                time.sleep(0.1)

            while self.user_data['waiting_on_image']:
                time.sleep(0.1)

            self.active_exposure = False
            self.user_data['waiting_on_image'] = False
            self.user_data['waiting_on_metadata'] = False

            self._processMetadata()

            self._queueImage()


    def getCcdExposureStatus(self):
        # returns camera_ready, exposure_state
        if self.user_data['waiting_on_metadata']:
            return False, 'BUSY'

        elif self.user_data['waiting_on_image']:
            return False, 'BUSY'


        if self.active_exposure:
            self.active_exposure = False

            self._processMetadata()

            self._queueImage()


        return True, 'READY'


    def abortCcdExposure(self):
        import paho.mqtt.properties as mqtt_props
        from paho.mqtt.packettypes import PacketTypes

        logger.warning('Aborting exposure')

        self.active_exposure = False
        self.user_data['waiting_on_image'] = False
        self.user_data['waiting_on_metadata'] = False


        user_properties = mqtt_props.Properties(PacketTypes.PUBLISH)
        user_properties.UserProperty = [
            ("Content-Type", "application/json"),
        ]


        payload = {
            'action' : 'abortCcdExposure',
            'kwargs' : {},
        }

        self.client.publish(self.exposure_topic, payload=json.dumps(payload), qos=self.qos, retain=False, properties=user_properties)


    def on_message(self, client, userdata, message):
        # The metadata should always be received first, the image data last

        if message.topic == self.metadata_topic:
            logger.info('Received metadata message')

            try:
                metadata_data = json.loads(message.payload)
            except ValueError as e:
                logger.error('JSON parse error: %s', str(e))
                metadata_data = {}

            with io.open(str(self.current_metadata_file_p), 'w') as f_metadata:
                json.dump(metadata_data, f_metadata)

            userdata['waiting_on_metadata'] = False

            return
        elif message.topic == self.image_topic:
            logger.info('Received image message')
            with io.open(str(self.current_exposure_file_p), 'wb') as f_image:
                f_image.write(message.payload)

            userdata['waiting_on_image'] = False

            return

        logger.error('Unknown topic: %s', message.topic)


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
            logger.info('Subscribing to image topic %s', self.image_topic)
            client.subscribe(self.image_topic)

            logger.info('Subscribing to metadata topic %s', self.metadata_topic)
            client.subscribe(self.metadata_topic)


class IndiClientLibCameraImx477Mqtt(IndiClientLibCameraMqttGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx477Mqtt, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'imx477 MQTT'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1.0,
            'max_gain'      : 22.26,
            'min_exposure'  : 0.000114,
            'max_exposure'  : 694.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4056:3040:12',
            1 : '',
            2 : '--mode 2028:1520:12',
            4 : '--mode 1332:990:10',  # cropped
        }


class IndiClientLibCameraImx378Mqtt(IndiClientLibCameraMqttGeneric):
    # this model is almost identical to the imx477

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx378Mqtt, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'imx378 MQTT'

        self.camera_info = {
            'width'         : 4056,
            'height'        : 3040,
            'pixel'         : 1.55,
            'min_gain'      : 1.0,
            'max_gain'      : 22.26,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000114,
            'max_exposure'  : 694.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4056:3040:12',
            1 : '',
            2 : '--mode 2028:1520:12',
            4 : '--mode 1332:990:10',  # cropped
        }


class IndiClientLibCameraImx708Mqtt(IndiClientLibCameraMqttGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraImx708Mqtt, self).__init__(*args, **kwargs)

        self.ccd_device_name = 'imx708 MQTT'

        self.camera_info = {
            'width'         : 4608,
            'height'        : 2592,
            'pixel'         : 1.4,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000026,
            'max_exposure'  : 220.0,
            'cfa'           : 'BGGR',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            #1 : '--mode 4608:2592:10',
            1 : '',
            2 : '--mode 2304:1296:10',
            4 : '--mode 1536:864:10',  # cropped
        }


class IndiClientLibCameraOv64a40OwlSightMqtt(IndiClientLibCameraMqttGeneric):

    def __init__(self, *args, **kwargs):
        super(IndiClientLibCameraOv64a40OwlSightMqtt, self).__init__(*args, **kwargs)

        self.ccd_device_name = '64MP OwlSight MQTT'

        self.camera_info = {
            'width'         : 9152,
            'height'        : 6944,
            'pixel'         : 1.008,
            'min_gain'      : 1.0,
            'max_gain'      : 16.0,
            'min_binning'   : 1,
            'max_binning'   : 4,
            'min_exposure'  : 0.000580,
            'max_exposure'  : 910.0,
            'cfa'           : 'RGGB',
            'bit_depth'     : 16,
        }

        self._binmode_options = {
            1 : '',
            #1 : '--mode 9152:6944:10',
            2 : '--mode 4624:3472:10',  # bin modes do not work well, exposure is not linear
            4 : '--mode 2312:1736:10',
        }

