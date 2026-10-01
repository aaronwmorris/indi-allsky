import sys
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

if 'micropython' not in sys.modules:
    mock_mp = MagicMock()
    mock_mp.const = lambda x: x
    sys.modules['micropython'] = mock_mp

if 'adafruit_bus_device' not in sys.modules:
    mock_abd = MagicMock()
    sys.modules['adafruit_bus_device'] = mock_abd
    sys.modules['adafruit_bus_device.i2c_device'] = mock_abd.i2c_device

if 'busio' not in sys.modules:
    mock_busio = MagicMock()
    sys.modules['busio'] = mock_busio

from indi_allsky.devices.controllers.dockerpi import DockerPi4ChannelRelay

from indi_allsky.devices.exceptions import DeviceControlException
from indi_allsky.devices.dew_heaters.dewHeaterBase import DewHeaterBase
from indi_allsky.devices.dew_heaters.dewHeaterSimulator import DewHeaterSimulator
from indi_allsky.devices.dew_heaters.dewHeaterStandard import DewHeaterStandard
from indi_allsky.devices.dew_heaters.dewHeaterDockerPi4ChannelRelay import DewHeaterDockerPi4ChannelRelay_I2C
from indi_allsky.devices.dew_heaters.dewHeaterMotorKit import DewHeaterMotorKitPwm
from indi_allsky.devices.dew_heaters.dewHeaterMqtt import (
    DewHeaterMqttBase,
    DewHeaterMqttStandard,
    DewHeaterMqttPwm,
)
from indi_allsky.devices.dew_heaters.dewHeaterPwm import DewHeaterPwm
from indi_allsky.devices.dew_heaters.dewHeaterSerialPwm import DewHeaterSerialPwm
from indi_allsky.devices.dew_heaters.dewHeaterSoftwarePwm import (
    DewHeaterSoftwarePwmRpiGpio,
    DewHeaterSoftwarePwmGpiozero,
)
from indi_allsky.devices.dew_heaters import (
    dew_heater_simulator,
    blinka_dew_heater_pwm,
    blinka_dew_heater_standard,
    blinka_dew_heater_digital,
    dew_heater_dockerpi_4channel_relay,
    serial_dew_heater_pwm,
    rpigpio_dew_heater_software_pwm,
    gpiozero_dew_heater_software_pwm,
    motorkit_dew_heater_pwm,
    mqtt_dew_heater_standard,
    mqtt_dew_heater_pwm,
)


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- DewHeaterBase & DewHeaterSimulator ---

def test_dew_heater_base():
    config = {'DEVICE': {}}
    heater = DewHeaterBase(config)
    assert heater.config == config
    heater.deinit()


def test_dew_heater_simulator():
    config = {'DEVICE': {}}
    heater = DewHeaterSimulator(config)
    assert heater.state == -1
    heater.state = 100
    assert heater.state == 0
    heater.disable()
    assert heater.state == 0
    heater.deinit()


# --- DewHeaterStandard ---

def test_dew_heater_standard():
    mock_board = MagicMock()
    mock_board.D12 = 'D12'
    mock_digitalio = MagicMock()
    mock_pin = MagicMock()
    mock_digitalio.DigitalInOut.return_value = mock_pin
    mock_digitalio.Direction.OUTPUT = 'OUTPUT'

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        # Normal logic (invert_output=False)
        heater = DewHeaterStandard({}, pin_1_name='D12', invert_output=False)
        assert heater.ON == 1
        assert heater.OFF == 0
        assert heater.state == -1

        heater.state = 1
        assert heater.state == 100
        assert mock_pin.value == 1

        heater.state = 0
        assert heater.state == 0
        assert mock_pin.value == 0

        heater.disable()
        assert heater.state == 0

        heater.deinit()
        mock_pin.deinit.assert_called_once()

        # Inverted logic (invert_output=True)
        heater_inv = DewHeaterStandard({}, pin_1_name='D12', invert_output=True)
        assert heater_inv.ON == 0
        assert heater_inv.OFF == 1

        heater_inv.state = 1
        assert mock_pin.value == 0
        assert heater_inv.state == 100

        heater_inv.state = 0
        assert mock_pin.value == 1
        assert heater_inv.state == 0


def test_dew_heater_standard_exception():
    mock_board = MagicMock()
    mock_digitalio = MagicMock()
    mock_digitalio.DigitalInOut.side_effect = RuntimeError("GPIO Busy")

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        with pytest.raises(DeviceControlException):
            DewHeaterStandard({}, pin_1_name='D12', invert_output=False)


# --- DewHeaterDockerPi4ChannelRelay_I2C ---

def test_dew_heater_dockerpi_relay():
    mock_board = MagicMock()
    mock_controller = MagicMock()

    with patch('indi_allsky.devices.controllers.dockerpi.DockerPi4ChannelRelay', return_value=mock_controller) as mock_cls, \
         patch.dict(sys.modules, {'board': mock_board}):
        mock_cls.RELAY1 = 1

        # Normal logic
        heater = DewHeaterDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY1',
            invert_output=False,
        )
        assert heater.ON == 1
        assert heater.OFF == 0
        assert heater.state == -1

        heater.state = 1
        mock_controller.set_relay.assert_called_with(1, 1)
        assert heater.state == 100

        heater.state = 0
        mock_controller.set_relay.assert_called_with(1, 0)
        assert heater.state == 0

        heater.disable()
        assert heater.state == 0

        heater.deinit()

        # Inverted logic
        heater_inv = DewHeaterDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY1',
            invert_output=True,
        )
        assert heater_inv.ON == 0
        assert heater_inv.OFF == 1

        heater_inv.state = 1
        mock_controller.set_relay.assert_called_with(1, 0)
        assert heater_inv.state == 100

        heater_inv.state = 0
        mock_controller.set_relay.assert_called_with(1, 1)
        assert heater_inv.state == 0


# --- DewHeaterMotorKitPwm ---

def test_dew_heater_motorkit_pwm():
    mock_board = MagicMock()
    mock_motorkit_mod = MagicMock()
    mock_kit = MagicMock()
    mock_motor = MagicMock()
    mock_kit.motor1 = mock_motor
    mock_motorkit_mod.MotorKit.return_value = mock_kit

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_motorkit': mock_motorkit_mod}):
        heater = DewHeaterMotorKitPwm(
            {},
            i2c_address='0x60',
            pin_1_name='motor1',
            invert_output=False,
        )
        assert heater.state == -1

        # Out of bounds
        heater.state = -5
        assert heater.state == -1
        heater.state = 105
        assert heater.state == -1

        # Valid setting
        heater.state = 50
        assert mock_motor.throttle == 0.5
        assert heater.state == 50

        heater.disable()
        assert heater.state == 0
        assert mock_motor.throttle == 0.0

        heater.deinit()

        # Inverted logic
        heater_inv = DewHeaterMotorKitPwm(
            {},
            i2c_address='0x60',
            pin_1_name='motor1',
            invert_output=True,
        )
        heater_inv.state = 40
        assert mock_motor.throttle == 0.6
        assert heater_inv.state == 40


# --- DewHeaterMqttBase, DewHeaterMqttStandard, DewHeaterMqttPwm ---

def test_dew_heater_mqtt_base_and_callbacks():
    mock_client = MagicMock()
    config = {
        'DEVICE': {
            'MQTT_TRANSPORT': 'tcp',
            'MQTT_PROTOCOL': 'MQTTv5',
            'MQTT_HOST': 'mqtt.local',
            'MQTT_PORT': 1883,
            'MQTT_USERNAME': 'user',
            'MQTT_PASSWORD': 'password',
            'MQTT_TLS': True,
            'MQTT_CERT_BYPASS': False,
            'MQTT_QOS': 1,
        },
    }

    with patch('paho.mqtt.client.Client', return_value=mock_client):
        heater = DewHeaterMqttBase(config, pin_1_name='allsky/dew_heater')
        assert heater.topic == 'allsky/dew_heater'
        assert heater.qos == 1
        mock_client.username_pw_set.assert_called_with(username='user', password='password')
        mock_client.tls_set.assert_called_once()
        mock_client.connect.assert_called_with('mqtt.local', port=1883)
        mock_client.loop_start.assert_called_once()

        # Callbacks
        reason_ok = MagicMock()
        reason_ok.is_failure = False
        heater.on_connect(mock_client, None, None, reason_ok, None)

        reason_fail = MagicMock()
        reason_fail.is_failure = True
        heater.on_connect(mock_client, None, None, reason_fail, None)

        heater.on_disconnect(mock_client, None, None, 'disconnected', None)
        heater.on_publish(mock_client, None, 1, 0, None)

        heater.deinit()
        mock_client.disconnect.assert_called_once()
        mock_client.loop_stop.assert_called_once()

        # Test cert_bypass=True with TLS
        heater_bypass = DewHeaterMqttBase(
            {
                'DEVICE': {
                    'MQTT_TLS': True,
                    'MQTT_CERT_BYPASS': True,
                },
            },
            pin_1_name='allsky/dew_heater_bypass',
        )
        mock_client.tls_set.assert_called_with(
            ca_certs='/etc/ssl/certs/ca-certificates.crt',
            cert_reqs=ssl.CERT_NONE,
        )
        heater_bypass.deinit()

        # Test username='' (empty username branch) and TLS=False
        heater_no_auth = DewHeaterMqttBase(
            {
                'DEVICE': {
                    'MQTT_USERNAME': '',
                    'MQTT_TLS': False,
                },
            },
            pin_1_name='allsky/dew_heater_noauth',
        )
        heater_no_auth.deinit()


def test_dew_heater_mqtt_base_connection_refused_and_unknown_protocol():
    mock_client = MagicMock()
    mock_client.connect.side_effect = ConnectionRefusedError("Refused")

    with patch('paho.mqtt.client.Client', return_value=mock_client):
        heater = DewHeaterMqttBase(
            {'DEVICE': {'MQTT_TLS': False, 'MQTT_CERT_BYPASS': True}},
            pin_1_name='allsky/dew_heater',
        )
        assert heater.topic == 'allsky/dew_heater'

    # Unknown protocol
    with pytest.raises(AttributeError):
        DewHeaterMqttBase(
            {'DEVICE': {'MQTT_PROTOCOL': 'INVALID_PROTO'}},
            pin_1_name='allsky/dew_heater',
        )


def test_dew_heater_mqtt_standard():
    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client):
        # Normal logic
        heater = DewHeaterMqttStandard(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/dew_heater_std',
            invert_output=False,
        )
        assert heater.ON == 100
        assert heater.OFF == 0

        heater.state = 1
        assert heater.state == 100
        mock_client.publish.assert_called()
        assert b'"state": 100' in mock_client.publish.call_args[1]['payload'].encode()

        heater.state = 0
        assert heater.state == 0
        assert b'"state": 0' in mock_client.publish.call_args[1]['payload'].encode()

        heater.disable()
        assert heater.state == 0

        # Inverted logic
        heater_inv = DewHeaterMqttStandard(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/dew_heater_std',
            invert_output=True,
        )
        assert heater_inv.ON == 0
        assert heater_inv.OFF == 100

        heater_inv.state = 1
        assert heater_inv.state == 100
        assert b'"state": 0' in mock_client.publish.call_args[1]['payload'].encode()

        heater_inv.state = 0
        assert heater_inv.state == 0
        assert b'"state": 100' in mock_client.publish.call_args[1]['payload'].encode()


def test_dew_heater_mqtt_pwm():
    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client):
        # Normal logic
        heater = DewHeaterMqttPwm(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/dew_heater_pwm',
            invert_output=False,
        )
        # Bounds checks
        heater.state = -1
        assert heater.state == -1
        heater.state = 101
        assert heater.state == -1

        heater.state = 65
        assert heater.state == 65
        assert b'"state": 65' in mock_client.publish.call_args[1]['payload'].encode()

        heater.disable()
        assert heater.state == 0

        # Inverted logic
        heater_inv = DewHeaterMqttPwm(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/dew_heater_pwm',
            invert_output=True,
        )
        heater_inv.state = 65
        assert heater_inv.state == 65
        assert b'"state": 35' in mock_client.publish.call_args[1]['payload'].encode()


# --- DewHeaterPwm ---

def test_dew_heater_pwm():
    mock_board = MagicMock()
    mock_board.D12 = 'D12'
    mock_pwmio = MagicMock()
    mock_pwm_obj = MagicMock()
    mock_pwmio.PWMOut.return_value = mock_pwm_obj

    with patch.dict(sys.modules, {'board': mock_board, 'pwmio': mock_pwmio}):
        heater = DewHeaterPwm(
            {},
            pin_1_name='D12',
            invert_output=False,
            pwm_frequency=25000,
        )
        assert heater.state == -1

        # Bounds checks
        heater.state = -1
        assert heater.state == -1
        heater.state = 101
        assert heater.state == -1

        # Normal duty cycle
        heater.state = 50
        assert heater.state == 50
        assert mock_pwm_obj.duty_cycle == int(65535 * 0.5)

        heater.disable()
        assert heater.state == 0

        heater.deinit()
        mock_pwm_obj.deinit.assert_called_once()

        # Inverted duty cycle
        heater_inv = DewHeaterPwm(
            {},
            pin_1_name='D12',
            invert_output=True,
            pwm_frequency=25000,
        )
        heater_inv.state = 20
        assert heater_inv.state == 20
        assert mock_pwm_obj.duty_cycle == int(65535 * 0.8)


def test_dew_heater_pwm_exception():
    mock_board = MagicMock()
    mock_pwmio = MagicMock()
    mock_pwmio.PWMOut.side_effect = RuntimeError("PWM channel busy")

    with patch.dict(sys.modules, {'board': mock_board, 'pwmio': mock_pwmio}):
        with pytest.raises(DeviceControlException):
            DewHeaterPwm(
                {},
                pin_1_name='D12',
                invert_output=False,
                pwm_frequency=25000,
            )


# --- DewHeaterSerialPwm ---

def test_dew_heater_serial_pwm(tmp_path):
    mock_port = tmp_path / "ttyUSB0"
    mock_port.touch()

    class MockSerialException(Exception):
        pass

    mock_serial_mod = MagicMock()
    mock_serial_mod.SerialException = MockSerialException
    mock_ser_instance = MagicMock()
    mock_serial_mod.Serial.return_value.__enter__.return_value = mock_ser_instance

    with patch('indi_allsky.devices.dew_heaters.dewHeaterSerialPwm.Path.joinpath', return_value=mock_port), \
         patch.dict(sys.modules, {'serial': mock_serial_mod}):

        heater = DewHeaterSerialPwm({}, pin_1_name='ttyUSB0')
        assert heater.state == -1

        # Bounds
        heater.state = -10
        assert heater.state == -1
        heater.state = 110
        assert heater.state == -1

        # Valid setting
        heater.state = 75
        assert heater.state == 75
        mock_ser_instance.write.assert_called_with(b'H75\n')

        heater.disable()
        assert heater.state == 0

        heater.deinit()

        # Serial error handling
        mock_ser_instance.write.side_effect = MockSerialException("Port closed")
        with pytest.raises(DeviceControlException):
            heater.state = 80


def test_dew_heater_serial_pwm_port_missing():
    with patch('indi_allsky.devices.dew_heaters.dewHeaterSerialPwm.Path.joinpath', return_value=Path('/nonexistent/port')):
        with pytest.raises(DeviceControlException, match='Serial port does not exist'):
            DewHeaterSerialPwm({}, pin_1_name='nonexistent_port')


# --- DewHeaterSoftwarePwmRpiGpio ---

def test_dew_heater_software_pwm_rpigpio():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_pwm_obj = MagicMock()
    mock_gpio.PWM.return_value = mock_pwm_obj

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        heater = DewHeaterSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=False)
        assert heater.state == -1
        mock_gpio.setup.assert_called_with(18, mock_gpio.OUT)
        mock_pwm_obj.start.assert_called_with(0)

        # Bounds
        heater.state = -5
        assert heater.state == -1
        heater.state = 105
        assert heater.state == -1

        # Valid
        heater.state = 60
        assert heater.state == 60
        mock_pwm_obj.ChangeDutyCycle.assert_called_with(60)

        heater.disable()
        assert heater.state == 0

        heater.deinit()

        # Inverted
        heater_inv = DewHeaterSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=True)
        heater_inv.state = 60
        assert heater_inv.state == 60
        mock_pwm_obj.ChangeDutyCycle.assert_called_with(40)


def test_dew_heater_software_pwm_rpigpio_exception():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_gpio.setup.side_effect = RuntimeError("GPIO busy")

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        with pytest.raises(DeviceControlException):
            DewHeaterSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=False)


# --- DewHeaterSoftwarePwmGpiozero ---

def test_dew_heater_software_pwm_gpiozero():
    mock_gpiozero = MagicMock()
    mock_pwm_device = MagicMock()
    mock_gpiozero.PWMOutputDevice.return_value = mock_pwm_device

    with patch.dict(sys.modules, {'gpiozero': mock_gpiozero}):
        heater = DewHeaterSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=False)
        assert heater.state == -1

        # Bounds
        heater.state = -1
        assert heater.state == -1
        heater.state = 101
        assert heater.state == -1

        # Valid
        heater.state = 70
        assert heater.state == 70
        assert mock_pwm_device.value == 0.7

        heater.disable()
        assert heater.state == 0

        heater.deinit()

        # Inverted
        heater_inv = DewHeaterSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=True)
        heater_inv.state = 70
        assert heater_inv.state == 70
        assert mock_pwm_device.value == pytest.approx(0.3)


def test_dew_heater_software_pwm_gpiozero_exception():
    mock_gpiozero = MagicMock()
    mock_gpiozero.PWMOutputDevice.side_effect = RuntimeError("Pin busy")

    with patch.dict(sys.modules, {'gpiozero': mock_gpiozero}):
        with pytest.raises(DeviceControlException):
            DewHeaterSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=False)


# --- Module exports check ---

def test_dew_heater_exports():
    assert dew_heater_simulator is DewHeaterSimulator
    assert blinka_dew_heater_pwm is DewHeaterPwm
    assert blinka_dew_heater_standard is DewHeaterStandard
    assert blinka_dew_heater_digital is DewHeaterStandard
    assert dew_heater_dockerpi_4channel_relay is DewHeaterDockerPi4ChannelRelay_I2C
    assert serial_dew_heater_pwm is DewHeaterSerialPwm
    assert rpigpio_dew_heater_software_pwm is DewHeaterSoftwarePwmRpiGpio
    assert gpiozero_dew_heater_software_pwm is DewHeaterSoftwarePwmGpiozero
    assert motorkit_dew_heater_pwm is DewHeaterMotorKitPwm
    assert mqtt_dew_heater_standard is DewHeaterMqttStandard
    assert mqtt_dew_heater_pwm is DewHeaterMqttPwm
