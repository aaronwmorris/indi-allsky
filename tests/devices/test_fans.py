import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky.devices.exceptions import DeviceControlException
from indi_allsky.devices.fans.fanBase import FanBase
from indi_allsky.devices.fans.fanSimulator import FanSimulator
from indi_allsky.devices.fans.fanStandard import FanStandard
from indi_allsky.devices.fans.fanDockerPi4ChannelRelay import FanDockerPi4ChannelRelay_I2C
from indi_allsky.devices.fans.fanMotorKit import FanMotorKitPwm
from indi_allsky.devices.fans.fanMqtt import FanMqttBase, FanMqttStandard, FanMqttPwm
from indi_allsky.devices.fans.fanPwm import FanPwm
from indi_allsky.devices.fans.fanSerialPwm import FanSerialPwm
from indi_allsky.devices.fans.fanSoftwarePwm import FanSoftwarePwmRpiGpio, FanSoftwarePwmGpiozero
from indi_allsky.devices.fans import (
    fan_simulator,
    blinka_fan_pwm,
    blinka_fan_standard,
    fan_dockerpi_4channel_relay,
    serial_fan_pwm,
    rpigpio_fan_software_pwm,
    gpiozero_fan_software_pwm,
    motorkit_fan_pwm,
    mqtt_fan_standard,
    mqtt_fan_pwm,
)


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- FanBase & FanSimulator ---

def test_fan_base():
    config = {'DEVICE': {}}
    fan = FanBase(config)
    assert fan.config == config
    fan.deinit()  # No-op


def test_fan_simulator():
    config = {'DEVICE': {}}
    fan = FanSimulator(config)
    assert fan.state == -1
    fan.state = 100
    assert fan.state == 0  # Simulator intentionally stays 0
    fan.disable()
    assert fan.state == 0


# --- FanStandard ---

def test_fan_standard():
    mock_board = MagicMock()
    mock_board.D18 = 'D18'
    mock_digitalio = MagicMock()
    mock_pin = MagicMock()
    mock_digitalio.DigitalInOut.return_value = mock_pin
    mock_digitalio.Direction.OUTPUT = 'OUTPUT'

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        # Normal logic (invert_output=False)
        fan = FanStandard({}, pin_1_name='D18', invert_output=False)
        assert fan.ON == 1
        assert fan.OFF == 0
        assert fan.state == 0

        fan.state = 1
        assert fan.state == 100
        assert mock_pin.value == 1

        fan.state = 0
        assert fan.state == 0
        assert mock_pin.value == 0

        fan.disable()
        assert fan.state == 0

        fan.deinit()
        mock_pin.deinit.assert_called_once()

        # Inverted logic (invert_output=True)
        fan_inv = FanStandard({}, pin_1_name='D18', invert_output=True)
        assert fan_inv.ON == 0
        assert fan_inv.OFF == 1

        fan_inv.state = 1
        assert mock_pin.value == 0
        assert fan_inv.state == 100

        fan_inv.state = 0
        assert mock_pin.value == 1
        assert fan_inv.state == 0


def test_fan_standard_exception():
    mock_board = MagicMock()
    mock_digitalio = MagicMock()
    mock_digitalio.DigitalInOut.side_effect = RuntimeError("GPIO Busy")

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        with pytest.raises(DeviceControlException):
            FanStandard({}, pin_1_name='D18', invert_output=False)


# --- FanDockerPi4ChannelRelay_I2C ---

def test_fan_dockerpi_relay():
    mock_board = MagicMock()
    mock_controller = MagicMock()

    with patch('indi_allsky.devices.controllers.dockerpi.DockerPi4ChannelRelay', return_value=mock_controller) as mock_cls, \
         patch.dict(sys.modules, {'board': mock_board}):
        mock_cls.RELAY1 = 1

        # Normal logic
        fan = FanDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY1',
            invert_output=False,
        )
        assert fan.ON == 1
        assert fan.OFF == 0

        fan.state = 1
        mock_controller.set_relay.assert_called_with(1, 1)
        assert fan.state == 100

        fan.state = 0
        mock_controller.set_relay.assert_called_with(1, 0)
        assert fan.state == 0

        fan.disable()
        assert fan.state == 0

        # Inverted logic
        fan_inv = FanDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY1',
            invert_output=True,
        )
        assert fan_inv.ON == 0
        assert fan_inv.OFF == 1

        fan_inv.state = 1
        mock_controller.set_relay.assert_called_with(1, 0)
        assert fan_inv.state == 100

        fan_inv.state = 0
        mock_controller.set_relay.assert_called_with(1, 1)
        assert fan_inv.state == 0


# --- FanMotorKitPwm ---

def test_fan_motorkit_pwm():
    mock_board = MagicMock()
    mock_motorkit_mod = MagicMock()
    mock_kit = MagicMock()
    mock_motor = MagicMock()
    mock_kit.motor1 = mock_motor
    mock_motorkit_mod.MotorKit.return_value = mock_kit

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_motorkit': mock_motorkit_mod}):
        fan = FanMotorKitPwm(
            {},
            i2c_address='0x60',
            pin_1_name='motor1',
            invert_output=False,
        )
        assert fan.state == -1

        # Out of bounds
        fan.state = -5
        assert fan.state == -1
        fan.state = 105
        assert fan.state == -1

        # Valid setting
        fan.state = 50
        assert mock_motor.throttle == 0.5
        assert fan.state == 50

        fan.disable()
        assert fan.state == 0
        assert mock_motor.throttle == 0.0

        fan.deinit()

        # Inverted logic
        fan_inv = FanMotorKitPwm(
            {},
            i2c_address='0x60',
            pin_1_name='motor1',
            invert_output=True,
        )
        fan_inv.state = 40
        assert mock_motor.throttle == 0.6
        assert fan_inv.state == 40


# --- FanMqttBase, FanMqttStandard, FanMqttPwm ---

def test_fan_mqtt_base_and_callbacks():
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
        fan = FanMqttBase(config, pin_1_name='allsky/fan')
        assert fan.topic == 'allsky/fan'
        assert fan.qos == 1
        mock_client.username_pw_set.assert_called_with(username='user', password='password')
        mock_client.tls_set.assert_called_once()
        mock_client.connect.assert_called_with('mqtt.local', port=1883)
        mock_client.loop_start.assert_called_once()

        # Callbacks
        reason_ok = MagicMock()
        reason_ok.is_failure = False
        fan.on_connect(mock_client, None, None, reason_ok, None)

        reason_fail = MagicMock()
        reason_fail.is_failure = True
        fan.on_connect(mock_client, None, None, reason_fail, None)

        fan.on_disconnect(mock_client, None, None, 'disconnected', None)
        fan.on_publish(mock_client, None, 1, 0, None)

        fan.deinit()
        mock_client.disconnect.assert_called_once()
        mock_client.loop_stop.assert_called_once()

        # Test cert_bypass=True with TLS
        import ssl
        fan_bypass = FanMqttBase(
            {
                'DEVICE': {
                    'MQTT_TLS': True,
                    'MQTT_CERT_BYPASS': True,
                },
            },
            pin_1_name='allsky/fan_bypass',
        )
        mock_client.tls_set.assert_called_with(
            ca_certs='/etc/ssl/certs/ca-certificates.crt',
            cert_reqs=ssl.CERT_NONE,
        )
        fan_bypass.deinit()



def test_fan_mqtt_base_connection_refused_and_unknown_protocol():
    mock_client = MagicMock()
    mock_client.connect.side_effect = ConnectionRefusedError("Refused")

    with patch('paho.mqtt.client.Client', return_value=mock_client):
        fan = FanMqttBase(
            {'DEVICE': {'MQTT_TLS': False, 'MQTT_CERT_BYPASS': True}},
            pin_1_name='allsky/fan',
        )
        assert fan.topic == 'allsky/fan'

    # Unknown protocol
    with pytest.raises(AttributeError):
        FanMqttBase(
            {'DEVICE': {'MQTT_PROTOCOL': 'INVALID_PROTO'}},
            pin_1_name='allsky/fan',
        )


def test_fan_mqtt_standard():
    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client):
        # Normal logic
        fan = FanMqttStandard(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/fan_std',
            invert_output=False,
        )
        assert fan.ON == 100
        assert fan.OFF == 0

        fan.state = 1
        assert fan.state == 100
        mock_client.publish.assert_called()
        assert b'"state": 100' in mock_client.publish.call_args[1]['payload'].encode()

        fan.state = 0
        assert fan.state == 0
        assert b'"state": 0' in mock_client.publish.call_args[1]['payload'].encode()

        fan.disable()
        assert fan.state == 0

        # Inverted logic
        fan_inv = FanMqttStandard(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/fan_std',
            invert_output=True,
        )
        assert fan_inv.ON == 0
        assert fan_inv.OFF == 100

        fan_inv.state = 1
        assert fan_inv.state == 100
        assert b'"state": 0' in mock_client.publish.call_args[1]['payload'].encode()


def test_fan_mqtt_pwm():
    mock_client = MagicMock()
    with patch('paho.mqtt.client.Client', return_value=mock_client):
        # Normal logic
        fan = FanMqttPwm(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/fan_pwm',
            invert_output=False,
        )
        # Bounds checks
        fan.state = -1
        assert fan.state == -1
        fan.state = 101
        assert fan.state == -1

        fan.state = 65
        assert fan.state == 65
        assert b'"state": 65' in mock_client.publish.call_args[1]['payload'].encode()

        # Inverted logic
        fan_inv = FanMqttPwm(
            {'DEVICE': {'MQTT_TLS': False}},
            pin_1_name='allsky/fan_pwm',
            invert_output=True,
        )
        fan_inv.state = 65
        assert fan_inv.state == 65
        assert b'"state": 35' in mock_client.publish.call_args[1]['payload'].encode()


# --- FanPwm ---

def test_fan_pwm():
    mock_board = MagicMock()
    mock_board.D12 = 'D12'
    mock_pwmio = MagicMock()
    mock_pwm_obj = MagicMock()
    mock_pwmio.PWMOut.return_value = mock_pwm_obj

    with patch.dict(sys.modules, {'board': mock_board, 'pwmio': mock_pwmio}):
        fan = FanPwm(
            {},
            pin_1_name='D12',
            invert_output=False,
            pwm_frequency=25000,
        )
        assert fan.state == -1

        # Bounds checks
        fan.state = -1
        assert fan.state == -1
        fan.state = 101
        assert fan.state == -1

        # Normal duty cycle
        fan.state = 50
        assert fan.state == 50
        assert mock_pwm_obj.duty_cycle == int(65535 * 0.5)

        fan.disable()
        assert fan.state == 0

        fan.deinit()
        mock_pwm_obj.deinit.assert_called_once()

        # Inverted duty cycle
        fan_inv = FanPwm(
            {},
            pin_1_name='D12',
            invert_output=True,
            pwm_frequency=25000,
        )
        fan_inv.state = 20
        assert fan_inv.state == 20
        assert mock_pwm_obj.duty_cycle == int(65535 * 0.8)


def test_fan_pwm_exception():
    mock_board = MagicMock()
    mock_pwmio = MagicMock()
    mock_pwmio.PWMOut.side_effect = RuntimeError("PWM channel busy")

    with patch.dict(sys.modules, {'board': mock_board, 'pwmio': mock_pwmio}):
        with pytest.raises(DeviceControlException):
            FanPwm(
                {},
                pin_1_name='D12',
                invert_output=False,
                pwm_frequency=25000,
            )


# --- FanSerialPwm ---

def test_fan_serial_pwm(tmp_path):
    mock_port = tmp_path / "ttyUSB0"
    mock_port.touch()

    class MockSerialException(Exception):
        pass

    mock_serial_mod = MagicMock()
    mock_serial_mod.SerialException = MockSerialException
    mock_ser_instance = MagicMock()
    mock_serial_mod.Serial.return_value.__enter__.return_value = mock_ser_instance

    with patch('indi_allsky.devices.fans.fanSerialPwm.Path.joinpath', return_value=mock_port), \
         patch.dict(sys.modules, {'serial': mock_serial_mod}):

        fan = FanSerialPwm({}, pin_1_name='ttyUSB0')
        assert fan.state == -1

        # Bounds
        fan.state = -10
        assert fan.state == -1
        fan.state = 110
        assert fan.state == -1

        # Valid setting
        fan.state = 75
        assert fan.state == 75
        mock_ser_instance.write.assert_called_with(b'F75\n')

        fan.disable()
        assert fan.state == 0

        # Serial error handling
        mock_ser_instance.write.side_effect = MockSerialException("Port closed")
        with pytest.raises(DeviceControlException):
            fan.state = 80


def test_fan_serial_pwm_port_missing():
    with patch('indi_allsky.devices.fans.fanSerialPwm.Path.joinpath', return_value=Path('/nonexistent/port')):
        with pytest.raises(DeviceControlException, match='Serial port does not exist'):
            FanSerialPwm({}, pin_1_name='nonexistent_port')


# --- FanSoftwarePwmRpiGpio ---

def test_fan_software_pwm_rpigpio():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_pwm_obj = MagicMock()
    mock_gpio.PWM.return_value = mock_pwm_obj

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        fan = FanSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=False)
        assert fan.state == -1
        mock_gpio.setup.assert_called_with(18, mock_gpio.OUT)
        mock_pwm_obj.start.assert_called_with(0)

        # Bounds
        fan.state = -5
        assert fan.state == -1
        fan.state = 105
        assert fan.state == -1

        # Valid
        fan.state = 60
        assert fan.state == 60
        mock_pwm_obj.ChangeDutyCycle.assert_called_with(60)

        fan.disable()
        assert fan.state == 0

        fan.deinit()

        # Inverted
        fan_inv = FanSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=True)
        fan_inv.state = 60
        assert fan_inv.state == 60
        mock_pwm_obj.ChangeDutyCycle.assert_called_with(40)


def test_fan_software_pwm_rpigpio_exception():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_gpio.setup.side_effect = RuntimeError("GPIO busy")

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        with pytest.raises(DeviceControlException):
            FanSoftwarePwmRpiGpio({}, pin_1_name='18', invert_output=False)


# --- FanSoftwarePwmGpiozero ---

def test_fan_software_pwm_gpiozero():
    mock_gpiozero = MagicMock()
    mock_pwm_device = MagicMock()
    mock_gpiozero.PWMOutputDevice.return_value = mock_pwm_device

    with patch.dict(sys.modules, {'gpiozero': mock_gpiozero}):
        fan = FanSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=False)
        assert fan.state == -1

        # Bounds
        fan.state = -1
        assert fan.state == -1
        fan.state = 101
        assert fan.state == -1

        # Valid
        fan.state = 70
        assert fan.state == 70
        assert mock_pwm_device.value == 0.7

        fan.disable()
        assert fan.state == 0

        fan.deinit()

        # Inverted
        fan_inv = FanSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=True)
        fan_inv.state = 70
        assert fan_inv.state == 70
        assert mock_pwm_device.value == pytest.approx(0.3)


def test_fan_software_pwm_gpiozero_exception():
    mock_gpiozero = MagicMock()
    mock_gpiozero.PWMOutputDevice.side_effect = RuntimeError("Pin busy")

    with patch.dict(sys.modules, {'gpiozero': mock_gpiozero}):
        with pytest.raises(DeviceControlException):
            FanSoftwarePwmGpiozero({}, pin_1_name='18', invert_output=False)


# --- Module exports check ---

def test_fan_exports():
    assert fan_simulator is FanSimulator
    assert blinka_fan_pwm is FanPwm
    assert blinka_fan_standard is FanStandard
    assert fan_dockerpi_4channel_relay is FanDockerPi4ChannelRelay_I2C
    assert serial_fan_pwm is FanSerialPwm
    assert rpigpio_fan_software_pwm is FanSoftwarePwmRpiGpio
    assert gpiozero_fan_software_pwm is FanSoftwarePwmGpiozero
    assert motorkit_fan_pwm is FanMotorKitPwm
    assert mqtt_fan_standard is FanMqttStandard
    assert mqtt_fan_pwm is FanMqttPwm
