import time
import json
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanMqttBase(FanBase):

    def __init__(self, *args, **kwargs):
        super(FanMqttBase, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        self.topic = str(pin_1_name)

        logger.info('Initializing MQTT FAN device using topic: %s', self.topic)

        import ssl
        import paho.mqtt.client as mqtt


        host = self.config.get('DEVICE', {}).get('MQTT_HOST', 'localhost')
        port = self.config.get('DEVICE', {}).get('MQTT_PORT', 8883)
        username = self.config.get('DEVICE', {}).get('MQTT_USERNAME', 'indi-allsky')
        password = self.config.get('DEVICE', {}).get('MQTT_PASSWORD', '')
        tls = self.config.get('DEVICE', {}).get('MQTT_TLS', True)
        cert_bypass = self.config.get('DEVICE', {}).get('MQTT_CERT_BYPASS', True)

        self._qos = self.config.get('DEVICE', {}).get('MQTT_QOS', 0)


        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


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


        self.client.connect(host, port=port)
        self.client.on_connect = self.on_connect
        self.client.on_publish = self.on_publish

        self.client.loop_start()


        self._state = 0

        time.sleep(1.0)


    @property
    def qos(self):
        return self._qos


    def disable(self):
        self.state = 0


    def deinit(self):
        super(FanMqttBase, self).deinit()

        self.client.disconnect()
        self.client.loop_stop()


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            logger.info('MQTT fan connected')


    def on_publish(self, client, userdata, mid, reason_code, properties):
        #logger.info('MQTT message published')
        pass


class FanMqttStandard(FanMqttBase):

    def __init__(self, *args, **kwargs):
        super(FanMqttStandard, self).__init__(*args, **kwargs)

        invert_output = kwargs['invert_output']


        if not invert_output:
            self.ON = 100
            self.OFF = 0
        else:
            self.ON = 0
            self.OFF = 100


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        payload = {}

        if new_state_b:
            logger.warning('Set fan state: 100%')
            payload['state'] = self.ON
            self.client.publish(self.topic, payload=json.dumps(payload), qos=self.qos, retain=True)
            self._state = 100
        else:
            logger.warning('Set fan state: 0%')
            payload['state'] = self.OFF
            self.client.publish(self.topic, payload=json.dumps(payload), qos=self.qos, retain=True)
            self._state = 0


class FanMqttPwm(FanMqttBase):

    def __init__(self, *args, **kwargs):
        super(FanMqttPwm, self).__init__(*args, **kwargs)

        self.invert_output = kwargs['invert_output']


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # duty cycle must be a percentage between 0 and 100
        new_state_i = int(new_state)

        if new_state_i < 0:
            logger.error('Duty cycle must be 0 or greater')
            return

        if new_state_i > 100:
            logger.error('Duty cycle must be 100 or less')
            return


        if not self.invert_output:
            new_duty_cycle = new_state_i
        else:
            new_duty_cycle = 100 - new_state_i

        payload = {
            'state' : new_duty_cycle,
        }

        logger.warning('Set fan state: %d%%', new_state_i)
        self.client.publish(self.topic, payload=json.dumps(payload), qos=self.qos, retain=True)

        self._state = new_state_i

