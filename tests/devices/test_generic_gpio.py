import sys
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
from indi_allsky.devices.generic.genericBase import GenericBase
from indi_allsky.devices.generic.gpioSimulator import GpioSimulator
from indi_allsky.devices.generic.gpioStandard import GpioStandard
from indi_allsky.devices.generic.gpioDockerPi4ChannelRelay import GpioDockerPi4ChannelRelay_I2C
from indi_allsky.devices.generic.gpioRpiGpio import GpioRpiGpio
from indi_allsky.devices.generic import (
    gpio_simulator,
    blinka_gpio_standard,
    gpio_dockerpi_4channel_relay,
    rpigpio_gpio_rpigpio,
)


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- GenericBase & GpioSimulator ---

def test_generic_base():
    config = {'DEVICE': {}}
    base = GenericBase(config)
    assert base.config == config
    base.deinit()


def test_gpio_simulator():
    config = {'DEVICE': {}}
    sim = GpioSimulator(config)
    assert sim.state == -1
    sim.state = 1
    assert sim.state == 0
    sim.disable()
    assert sim.state == 0
    sim.deinit()


# --- GpioStandard ---

def test_gpio_standard():
    mock_board = MagicMock()
    mock_board.D14 = 'D14'
    mock_digitalio = MagicMock()
    mock_pin = MagicMock()
    mock_digitalio.DigitalInOut.return_value = mock_pin
    mock_digitalio.Direction.OUTPUT = 'OUTPUT'

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        # Normal logic
        gpio = GpioStandard({}, pin_1_name='D14', invert_output=False)
        assert gpio.ON == 1
        assert gpio.OFF == 0
        assert gpio.ON_LEVEL == 'high'
        assert gpio.OFF_LEVEL == 'low'
        assert gpio.state == -1

        gpio.state = 1
        assert gpio.state == 1
        assert mock_pin.value == 1

        gpio.state = 0
        assert gpio.state == 0
        assert mock_pin.value == 0

        gpio.disable()
        assert gpio.state == 0

        gpio.deinit()
        mock_pin.deinit.assert_called_once()

        # Inverted logic
        gpio_inv = GpioStandard({}, pin_1_name='D14', invert_output=True)
        assert gpio_inv.ON == 0
        assert gpio_inv.OFF == 1
        assert gpio_inv.ON_LEVEL == 'low'
        assert gpio_inv.OFF_LEVEL == 'high'

        gpio_inv.state = 1
        assert mock_pin.value == 0
        assert gpio_inv.state == 1

        gpio_inv.state = 0
        assert mock_pin.value == 1
        assert gpio_inv.state == 0


def test_gpio_standard_exception():
    mock_board = MagicMock()
    mock_digitalio = MagicMock()
    mock_digitalio.DigitalInOut.side_effect = RuntimeError("Pin busy")

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        with pytest.raises(DeviceControlException):
            GpioStandard({}, pin_1_name='D14', invert_output=False)


# --- GpioDockerPi4ChannelRelay_I2C ---

def test_gpio_dockerpi_relay():
    mock_board = MagicMock()
    mock_controller = MagicMock()

    with patch('indi_allsky.devices.controllers.dockerpi.DockerPi4ChannelRelay', return_value=mock_controller) as mock_cls, \
         patch.dict(sys.modules, {'board': mock_board}):
        mock_cls.RELAY2 = 2

        # Normal logic
        gpio = GpioDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY2',
            invert_output=False,
        )
        assert gpio.ON == 1
        assert gpio.OFF == 0
        assert gpio.ON_LEVEL == 'high'
        assert gpio.OFF_LEVEL == 'low'
        assert gpio.state == -1

        gpio.state = 1
        mock_controller.set_relay.assert_called_with(2, 1)
        assert gpio.state == 100

        gpio.state = 0
        mock_controller.set_relay.assert_called_with(2, 0)
        assert gpio.state == 0

        gpio.disable()
        assert gpio.state == 0

        gpio.deinit()

        # Inverted logic
        gpio_inv = GpioDockerPi4ChannelRelay_I2C(
            {},
            i2c_address='0x10',
            pin_1_name='RELAY2',
            invert_output=True,
        )
        assert gpio_inv.ON == 0
        assert gpio_inv.OFF == 1
        assert gpio_inv.ON_LEVEL == 'low'
        assert gpio_inv.OFF_LEVEL == 'high'

        gpio_inv.state = 1
        mock_controller.set_relay.assert_called_with(2, 0)
        assert gpio_inv.state == 100

        gpio_inv.state = 0
        mock_controller.set_relay.assert_called_with(2, 1)
        assert gpio_inv.state == 0


# --- GpioRpiGpio ---

def test_gpio_rpigpio():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_gpio.input.return_value = 0

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        gpio = GpioRpiGpio({}, pin_1_name='21')
        assert gpio.state is False
        mock_gpio.setmode.assert_called_with(mock_gpio.BCM)
        mock_gpio.setup.assert_called_with(21, mock_gpio.OUT)

        gpio.state = True
        assert gpio.state is True
        mock_gpio.output.assert_called_with(21, mock_gpio.HIGH)

        gpio.state = False
        assert gpio.state is False
        mock_gpio.output.assert_called_with(21, mock_gpio.LOW)

        gpio.deinit()
        mock_gpio.cleanup.assert_called_with(21)


def test_gpio_rpigpio_exception():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_gpio.setup.side_effect = RuntimeError("GPIO busy")

    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        with pytest.raises(DeviceControlException):
            GpioRpiGpio({}, pin_1_name='21')


# --- Module exports check ---

def test_generic_gpio_exports():
    assert gpio_simulator is GpioSimulator
    assert blinka_gpio_standard is GpioStandard
    assert gpio_dockerpi_4channel_relay is GpioDockerPi4ChannelRelay_I2C
    assert rpigpio_gpio_rpigpio is GpioRpiGpio
