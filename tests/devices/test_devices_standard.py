import sys
from unittest.mock import MagicMock, patch
import pytest

# Ensure board and digitalio are mocked if not installed on standard Linux
if 'board' not in sys.modules:
    mock_board = MagicMock()
    mock_board.D12 = 'D12'
    mock_board.D13 = 'D13'
    mock_board.D14 = 'D14'
    sys.modules['board'] = mock_board

if 'digitalio' not in sys.modules:
    mock_dio = MagicMock()
    mock_dio.Direction.OUTPUT = 'OUTPUT'
    mock_dio.DigitalInOut = MagicMock()
    sys.modules['digitalio'] = mock_dio

from indi_allsky.devices.dew_heaters.dewHeaterStandard import DewHeaterStandard
from indi_allsky.devices.fans.fanStandard import FanStandard
from indi_allsky.devices.generic.gpioStandard import GpioStandard


def test_dew_heater_standard():
    with patch('time.sleep', return_value=None):
        heater = DewHeaterStandard(
            {},
            pin_1_name='D12',
            invert_output=False,
        )

        # Set ON
        heater.state = 100
        assert heater.state == 100
        assert heater.pin.value == 1

        # Set OFF
        heater.disable()
        assert heater.state == 0
        assert heater.pin.value == 0

        heater.deinit()


def test_fan_standard():
    with patch('time.sleep', return_value=None):
        fan = FanStandard(
            {},
            pin_1_name='D13',
            invert_output=True,
        )

        # Set ON (inverted logic)
        fan.state = 80
        assert fan.state == 100
        assert fan.pin.value == 0

        # Set OFF
        fan.disable()
        assert fan.state == 0
        assert fan.pin.value == 1

        fan.deinit()


def test_gpio_standard():
    with patch('time.sleep', return_value=None):
        gpio = GpioStandard(
            {},
            pin_1_name='D14',
            invert_output=False,
        )

        gpio.state = 1
        assert gpio.state == 1
        assert gpio.pin.value == 1

        gpio.disable()
        assert gpio.state == 0
        assert gpio.pin.value == 0

        gpio.deinit()
