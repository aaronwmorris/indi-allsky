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
    mock_dio.DigitalInOut = MagicMock()
    sys.modules['digitalio'] = mock_dio

from indi_allsky.devices.focusers.focuser_28byj import focuser_28byj_64, focuser_28byj_16


def test_focuser_28byj_64_move():
    with patch('time.sleep', return_value=None):
        focuser = focuser_28byj_64(
            {},
            pin_names=['D1', 'D2', 'D3', 'D4'],
        )

        # CW move
        steps_cw = focuser.move('cw', 6)
        assert steps_cw == 8

        # CCW move (negative steps)
        steps_ccw = focuser.move('ccw', 45)
        assert steps_ccw == -64

        focuser.deinit()


def test_focuser_28byj_16_move():
    with patch('time.sleep', return_value=None):
        focuser = focuser_28byj_16(
            {},
            pin_names=['D1', 'D2', 'D3', 'D4'],
        )

        steps_cw = focuser.move('cw', 90)
        assert steps_cw == 32

        focuser.deinit()
