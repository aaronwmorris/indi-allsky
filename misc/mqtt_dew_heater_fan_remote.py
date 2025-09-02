#!/usr/bin/env python3
##################################################################
# This script manages a dew heater and fan device via MQTT       #
##################################################################

### Requirements
#paho-mqtt >= 2.0.0
#Adafruit-Blinka
#gpiod
#gpiozero
#rpi-lgpio  (remove RPi.GPIO)


### Set pins here
DEW_HEATER_PIN = 'D12'
FAN_PIN = 'D13'
# software pwm pins will be integers


### MQTT settings
MQTT_HOSTNAME = 'localhost'
MQTT_PORT = 8883
MQTT_USERNAME = 'username'
MQTT_PASSWORD = 'password123'
MQTT_TLS = True
MQTT_CERT_BYPASS = True

MQTT_DEW_HEATER_TOPIC = 'dew_heater_topic'
MQTT_FAN_TOPIC = 'fan_topic'


import sys
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


class MqttDewHeaterFan(object):
    def __init__(self):
        try:
            ### Standard device (on/off)
            self.dew_heater = DeviceStandard('Dew Heater', DEW_HEATER_PIN)
            self.fan = DeviceStandard('Fan', FAN_PIN)

            ### PWM device
            #self.dew_heater = DevicePwm('Dew Heater', DEW_HEATER_PIN)
            #self.fan = DevicePwm('Fan', FAN_PIN)

            ### Software PWM device
            #self.dew_heater = DeviceSoftwarePwm('Dew Heater', DEW_HEATER_PIN)
            #self.fan = DeviceSoftwarePwm('Fan', FAN_PIN)
        except (AttributeError, NotImplementedError) as e:
            logger.error('Exception: %s', str(e))
            logger.warning('Your system may not support GPIO')
            sys.exit(1)


        self.client = None


    def sigint_handler(self, signum, frame):
        logger.warning('Caught INT signal, shutting down')

        self.client.disconnect()
        self.client.loop_stop()

        self.dew_heater.deinit()
        self.fan.deinit()

        sys.exit()


    def sigterm_handler(self, signum, frame):
        logger.warning('Caught TERM signal, shutting down')

        self.client.disconnect()
        self.client.loop_stop()

        self.dew_heater.deinit()
        self.fan.deinit()

        sys.exit()


    def main(self):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
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

        self.client.loop_forever()


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
            val = int(message.payload.decode())
        except ValueError as e:
            logger.error('MQTT data ValueError: %s', str(e))
            return


        logger.info('Topic: %s, value: %d', message.topic, val)


        if message.topic == MQTT_DEW_HEATER_TOPIC:
            self.dew_heater.state = val
        elif message.topic == MQTT_FAN_TOPIC:
            self.fan.state = val
        else:
            logger.error('MQTT unknown topic: %s', message.topic)
            return


    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            logger.error('Failed to connect: %s', reason_code)
        else:
            # we should always subscribe from on_connect callback to be sure
            # our subscribed is persisted across reconnections.
            logger.info('Subscribing to topic %s', MQTT_DEW_HEATER_TOPIC)
            client.subscribe(MQTT_DEW_HEATER_TOPIC)

            logger.info('Subscribing to topic %s', MQTT_FAN_TOPIC)
            client.subscribe(MQTT_FAN_TOPIC)


class DeviceStandard(object):
    def __init__(self, name, pin_name):
        self.name = name

        import board
        import digitalio

        logger.info('Initializing Standard %s device on pin %s', self.name, pin_name)

        pin = getattr(board, pin_name)


        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.OUTPUT

        self._state = 0


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set %s state: 100%', self.name)
            self.dew_heater_pin.value = 1
            self._dew_heater_state = 100
        else:
            logger.warning('Set %s state: 0%', self.name)
            self.dew_heater_pin.value = 0
            self._dew_heater_state = 0


    def deinit(self):
        self.pin.deinit()


class DevicePwm(object):
    def __init__(self, name, pin_name):
        self.name = name

        import board
        import pwmio

        logger.info('Initializing PWM %s device on pin %s', self.name, pin_name)

        pin = getattr(board, pin_name)

        self.pwm = pwmio.PWMOut(pin)

        self._state = 0


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


        new_duty_cycle = int(((2 ** 16) - 1) * new_state_i / 100)


        logger.warning('Set %s state: %d%%', self.name, new_state_i)
        self.pwm.duty_cycle = new_duty_cycle

        self._state = new_state_i


    def deinit(self):
        super(DevicePwm, self).deinit()
        self.pwm.deinit()


class DeviceSoftwarePwm(object):
    PWM_FREQUENCY = 100

    def __init__(self, name, pin_name):
        self.name = name

        pwm_pin = int(pin_name)

        logger.info('Initializing Software PWM %s device on pin %d (%d Hz)', self.name, pwm_pin, self.PWM_FREQUENCY)

        import RPi.GPIO as GPIO
        #GPIO.setmode(GPIO.BOARD)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pwm_pin, GPIO.OUT)
        self.pwm = GPIO.PWM(pwm_pin, self.PWM_FREQUENCY)
        self.pwm.start(0)


        #from gpiozero import PWMOutputDevice
        #logger.info('Initializing Software PWM FAN device (%d Hz)', self.PWM_FREQUENCY)
        #self.pwm = PWMOutputDevice(pwm_pin, initial_value=0, frequency=self.PWM_FREQUENCY)


        self._state = 0


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


        new_duty_cycle = new_state_i


        logger.warning('Set %s state: %d%%', self.name, new_state_i)
        self.pwm.ChangeDutyCycle(new_duty_cycle)

        self._state = new_state_i


    def deinit(self):
        pass


if __name__ == "__main__":
    dhf = MqttDewHeaterFan().main()

