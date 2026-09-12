from unittest.mock import patch
import pytest

from indi_allsky.focuser import IndiAllSkyFocuserInterface


def test_focuser_interface_simulator():
    config = {
        'FOCUSER': {
            'CLASSNAME': 'focuser_simulator',
            'GPIO_PIN_1': 'pin1',
            'GPIO_PIN_2': 'pin2',
            'GPIO_PIN_3': 'pin3',
            'GPIO_PIN_4': 'pin4',
            'I2C_ADDRESS': '0x60',
        }
    }

    interface = IndiAllSkyFocuserInterface(config)
    assert interface.focuser is not None

    with patch('time.sleep', return_value=None):
        steps = interface.move('cw', 10)
        assert steps == 10

    interface.deinit()
