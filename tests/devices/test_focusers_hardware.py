import sys
from unittest.mock import MagicMock, patch
import pytest

# Ensure board and digitalio are mocked if not installed
if 'board' not in sys.modules:
    mock_board = MagicMock()
    mock_board.D1 = 'D1'
    mock_board.D2 = 'D2'
    mock_board.D3 = 'D3'
    mock_board.D4 = 'D4'
    sys.modules['board'] = mock_board

if 'digitalio' not in sys.modules:
    mock_dio = MagicMock()
    mock_dio.Direction.OUTPUT = 'OUTPUT'
    mock_dio.DigitalInOut.side_effect = lambda *a, **kw: MagicMock()
    sys.modules['digitalio'] = mock_dio
else:
    sys.modules['digitalio'].DigitalInOut.side_effect = lambda *a, **kw: MagicMock()

from indi_allsky.devices.focusers.focuser_28byj import focuser_28byj_64, focuser_28byj_16


def test_focuser_28byj_64_move():
    with patch('time.sleep', return_value=None):
        focuser = focuser_28byj_64(
            {},
            pin_names=['D1', 'D2', 'D3', 'D4'],
        )

        assert len(focuser.pins) == 4

        # CW move (8 steps)
        steps_cw = focuser.move('cw', 6)
        assert steps_cw == 8
        # Pins are reset to 0 after move
        assert all(p.value == 0 for p in focuser.pins)

        # CCW move (negative steps)
        steps_ccw = focuser.move('ccw', 45)
        assert steps_ccw == -64
        assert all(p.value == 0 for p in focuser.pins)

        # Unsupported degree raises KeyError
        with pytest.raises(KeyError):
            focuser.move('cw', 999)

        # Deinit calls pin.deinit() on all pins
        focuser.deinit()
        for p in focuser.pins:
            p.deinit.assert_called_once()


def test_focuser_28byj_16_move():
    with patch('time.sleep', return_value=None):
        focuser = focuser_28byj_16(
            {},
            pin_names=['D1', 'D2', 'D3', 'D4'],
        )

        steps_cw = focuser.move('cw', 90)
        assert steps_cw == 32
        assert all(p.value == 0 for p in focuser.pins)

        focuser.deinit()
        for p in focuser.pins:
            p.deinit.assert_called_once()
