#import time
#import random
import logging

from .sensorBase import SensorBase
from ... import constants
#from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class MqttBrokerSensor(SensorBase):

    METADATA = {
        'name' : 'MQTT Broker',
        'description' : 'MQTT Broker Sensor',
        'count' : 5,
        'labels' : (
            'Topic 1',
            'Topic 2',
            'Topic 3',
            'Topic 4',
            'Topic 5',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(MqttBrokerSensor, self).__init__(*args, **kwargs)

        topics_str = kwargs['pin_1_name']
        topics = topics_str.split(',')
        self.topic_list = list(topics[:5])

        import ssl
        import paho.mqtt.client as mqtt

        logger.warning('Initializing [%s] MQTT Broker Sensor', self.name)

        self.data = {
            'data' : [0.0, 0.0, 0.0, 0.0, 0.0],
        }

        host = self.config.get('TEMP_SENSOR', {}).get('MQTT_HOST', 'localhost')
        port = self.config.get('TEMP_SENSOR', {}).get('MQTT_PORT', 8883)
        username = self.config.get('TEMP_SENSOR', {}).get('MQTT_USERNAME', 'indi-allsky')
        password = self.config.get('TEMP_SENSOR', {}).get('MQTT_PASSWORD', '')
        tls = self.config.get('TEMP_SENSOR', {}).get('MQTT_TLS', True)
        cert_bypass = self.config.get('TEMP_SENSOR', {}).get('MQTT_CERT_BYPASS', True)


        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.on_subscribe = self.on_subscribe
        #mqttc.on_unsubscribe = self.on_unsubscribe

        client.user_data_set(self.data)


        if username:
            client.username_pw_set(username=username, password=password)


        if tls:
            mq_tls = {
                'ca_certs'    : '/etc/ssl/certs/ca-certificates.crt',
                'cert_reqs'   : ssl.CERT_REQUIRED,
            }

            if cert_bypass:
                mq_tls['cert_reqs'] = ssl.CERT_NONE

            client.tls_set(**mq_tls)


        client.connect(host, port=port)
        client.loop_start()


    def update(self):
        logger.info('[%s] MQTT Broker - values: %0.3f, %0.3f, %0.3f, %0.3f, %0.3f', self.name, *self.data['data'])

        return self.data


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
        try:
            val = float(message.payload.decode())
        except ValueError as e:
            logger.error('MQTT data ValueError: %s', str(e))
            return

        try:
            idx = self.topic_list.index(message.topic)
        except ValueError:
            logger.error('MQTT unknown topic: %s', message.topic)
            return

        logger.info('MQTT Sensor received: %0.3f (%s)', val, message.topic)
        userdata['data'][idx] = val


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            # we should always subscribe from on_connect callback to be sure
            # our subscribed is persisted across reconnections.
            for topic in self.topic_list:
                logger.info('Subscribing to topic %s', topic)
                client.subscribe(topic)

