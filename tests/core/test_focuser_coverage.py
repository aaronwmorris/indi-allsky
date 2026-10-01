from unittest.mock import patch
import pytest

from indi_allsky.focuser import IndiAllSkyFocuserInterface


def test_focuser_default_simulator():
    # Empty FOCUSER dictionary tests line 16 defaulting to 'focuser_simulator'
    config = {
        'FOCUSER': {}
    }

    interface = IndiAllSkyFocuserInterface(config)
    assert interface.focuser is not None

    with patch('time.sleep', return_value=None):
        steps = interface.move('ccw', 5)
        assert steps == -5

    interface.deinit()


def test_focuser_missing_focuser_key():
    # Config without FOCUSER key at all
    config = {}

    interface = IndiAllSkyFocuserInterface(config)
    assert interface.focuser is not None
    interface.deinit()
