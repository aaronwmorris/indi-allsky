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

if 'serial' not in sys.modules:
    try:
        import serial  # noqa: F401
    except ImportError:
        mock_serial = MagicMock()
        mock_serial.SerialException = type('SerialException', (Exception,), {})
        mock_serial.Serial = MagicMock()
        sys.modules['serial'] = mock_serial

from indi_allsky.devices.focusers.focuser_28byj import focuser_28byj_64, focuser_28byj_16
from indi_allsky.devices.focusers.focuser_a4988 import focuser_a4988_nema17_full, focuser_a4988_nema17_half
from indi_allsky.devices.focusers.focuserSerial28byj import FocuserSerial28byj_64


def test_focuser_28byj_64_move():
    mock_pins = [MagicMock(name=f'pin_{i}') for i in range(4)]
    pin_iter = iter(mock_pins)
    with patch('time.sleep', return_value=None), \
         patch('digitalio.DigitalInOut', side_effect=lambda *a, **kw: next(pin_iter)):
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
    mock_pins = [MagicMock(name=f'pin_{i}') for i in range(4)]
    pin_iter = iter(mock_pins)
    with patch('time.sleep', return_value=None), \
         patch('digitalio.DigitalInOut', side_effect=lambda *a, **kw: next(pin_iter)):
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


def test_focuser_a4988_move():
    with patch('time.sleep', return_value=None), \
         patch('digitalio.DigitalInOut', side_effect=lambda *a, **kw: MagicMock()):
        focuser_full = focuser_a4988_nema17_full(
            {},
            pin_names=['D1', 'D2', 'D3'],
        )
        assert focuser_full.STEPS == 200
        steps = focuser_full.move('cw', 18)
        assert steps == 10
        focuser_full.deinit()

        focuser_half = focuser_a4988_nema17_half(
            {},
            pin_names=['D1', 'D2', 'D3'],
        )
        assert focuser_half.STEPS == 400
        steps_ccw = focuser_half.move('ccw', 18)
        assert steps_ccw == -20
        focuser_half.deinit()


def test_focuser_serial_28byj_move(tmp_path):
    fake_port = tmp_path / "ttyUSB0"
    fake_port.touch()

    mock_serial_inst = MagicMock()
    mock_serial_cls = MagicMock()
    mock_serial_cls.return_value.__enter__.return_value = mock_serial_inst
    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial = mock_serial_cls
    mock_serial_mod.SerialException = Exception

    with patch('pathlib.Path.exists', return_value=True), \
         patch('time.sleep', return_value=None), \
         patch.dict(sys.modules, {'serial': mock_serial_mod}):

        focuser = FocuserSerial28byj_64(
            {},
            pin_names=['ttyUSB0'],
        )

        steps_cw = focuser.move('cw', 45)
        assert steps_cw == 64
        mock_serial_inst.write.assert_called_once_with(b'S64\n')

        mock_serial_inst.reset_mock()
        steps_ccw = focuser.move('ccw', 90)
        assert steps_ccw == -128
        mock_serial_inst.write.assert_called_once_with(b'S-128\n')
