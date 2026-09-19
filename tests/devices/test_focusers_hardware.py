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

from indi_allsky.devices.exceptions import DeviceControlException
from indi_allsky.devices.focusers.focuserBase import FocuserBase
from indi_allsky.devices.focusers.focuser_28byj import focuser_28byj_64, focuser_28byj_16
from indi_allsky.devices.focusers.focuser_a4988 import focuser_a4988_nema17_full, focuser_a4988_nema17_half
from indi_allsky.devices.focusers.focuserSerial28byj import FocuserSerial28byj, FocuserSerial28byj_64
from indi_allsky.devices.focusers.focuserMotorKit import (
    FocuserMotorKitBase,
    FocuserMotorKitSingleStep,
    FocuserMotorKitDoubleStep,
    FocuserMotorKitInterleaveStep,
    FocuserMotorKitMicrostepStep,
)
from indi_allsky.devices.focusers import (
    focuser_simulator,
    blinka_focuser_28byj_64,
    blinka_focuser_28byj_16,
    blinka_focuser_a4988_nema17_full,
    blinka_focuser_a4988_nema17_half,
    serial_focuser_28byj_64,
    motorkit_focuser_single_step,
)


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


def test_focuser_base_move():
    focuser = FocuserBase({'DEVICE': {}})
    focuser.deinit()
    with pytest.raises(Exception, match='Not Implemented'):
        focuser.move('cw', 10)


def test_focuser_28byj_exception():
    with patch('digitalio.DigitalInOut', side_effect=RuntimeError("GPIO busy")):
        with pytest.raises(DeviceControlException):
            focuser_28byj_64({}, pin_names=['D1', 'D2', 'D3', 'D4'])


def test_focuser_a4988_exception():
    with patch('digitalio.DigitalInOut', side_effect=RuntimeError("GPIO busy")):
        with pytest.raises(DeviceControlException):
            focuser_a4988_nema17_full({}, pin_names=['D1', 'D2', 'D3'])


def test_focuser_serial_28byj_errors():
    with patch('pathlib.Path.exists', return_value=False):
        with pytest.raises(DeviceControlException, match='Serial port does not exist'):
            FocuserSerial28byj_64({}, pin_names=['nonexistent_tty'])

    mock_serial_inst = MagicMock()
    mock_serial_cls = MagicMock()
    mock_serial_cls.return_value.__enter__.return_value = mock_serial_inst
    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial = mock_serial_cls
    mock_serial_mod.SerialException = type('SerialException', (Exception,), {})

    with patch('pathlib.Path.exists', return_value=True), \
         patch('time.sleep', return_value=None), \
         patch.dict(sys.modules, {'serial': mock_serial_mod}):

        focuser = FocuserSerial28byj_64({}, pin_names=['ttyUSB0'])
        mock_serial_inst.write.side_effect = mock_serial_mod.SerialException("Write failure")
        with pytest.raises(DeviceControlException):
            focuser.move('cw', 45)


def test_focuser_motorkit():
    mock_board = MagicMock()
    mock_motorkit_mod = MagicMock()
    mock_kit = MagicMock()
    mock_stepper = MagicMock()
    mock_kit.stepper1 = mock_stepper
    mock_motorkit_mod.MotorKit.return_value = mock_kit

    mock_stepper_mod = MagicMock()
    mock_stepper_mod.FORWARD = 'FORWARD'
    mock_stepper_mod.BACKWARD = 'BACKWARD'
    mock_stepper_mod.SINGLE = 'SINGLE'
    mock_stepper_mod.DOUBLE = 'DOUBLE'
    mock_stepper_mod.INTERLEAVE = 'INTERLEAVE'
    mock_stepper_mod.MICROSTEP = 'MICROSTEP'

    with patch('time.sleep', return_value=None), \
         patch.dict(sys.modules, {
             'board': mock_board,
             'adafruit_motorkit': mock_motorkit_mod,
             'adafruit_motor': MagicMock(stepper=mock_stepper_mod),
             'adafruit_motor.stepper': mock_stepper_mod,
         }):

        # Base getStepStyle raises NotImplementedError
        base = FocuserMotorKitBase({}, pin_names=['stepper1'], i2c_address='0x60')
        with pytest.raises(NotImplementedError):
            base.getStepStyle()

        # SingleStep
        focuser_single = FocuserMotorKitSingleStep({}, pin_names=['stepper1'], i2c_address='0x60')
        assert focuser_single.getStepStyle() == 'SINGLE'
        steps_cw = focuser_single.move('cw', 10)
        assert steps_cw == 10
        assert mock_stepper.onestep.call_count == 10
        mock_stepper.onestep.assert_called_with(direction='FORWARD', style='SINGLE')
        assert mock_stepper.release.call_count == 2

        # DoubleStep CCW (steps becomes negative so range is 0 iterations, returns negative steps)
        mock_stepper.reset_mock()
        focuser_double = FocuserMotorKitDoubleStep({}, pin_names=['stepper1'], i2c_address='0x60')
        assert focuser_double.getStepStyle() == 'DOUBLE'
        steps_ccw = focuser_double.move('ccw', 10)
        assert steps_ccw == -10
        assert mock_stepper.onestep.call_count == 0

        # DoubleStep CW (step_factor = 0.5, so 10 * 0.5 = 5 steps)
        mock_stepper.reset_mock()
        steps_cw = focuser_double.move('cw', 10)
        assert steps_cw == 10
        assert mock_stepper.onestep.call_count == 5
        mock_stepper.onestep.assert_called_with(direction='FORWARD', style='DOUBLE')

        # InterleaveStep & MicrostepStep getStepStyle
        focuser_interleave = FocuserMotorKitInterleaveStep({}, pin_names=['stepper1'], i2c_address='0x60')
        assert focuser_interleave.getStepStyle() == 'INTERLEAVE'

        focuser_micro = FocuserMotorKitMicrostepStep({}, pin_names=['stepper1'], i2c_address='0x60')
        assert focuser_micro.getStepStyle() == 'MICROSTEP'

        # Exception handling in move
        mock_stepper.onestep.side_effect = RuntimeError("Stepper error")
        with pytest.raises(DeviceControlException):
            focuser_single.move('cw', 1)


def test_focuser_exports():
    assert blinka_focuser_28byj_64 is focuser_28byj_64
    assert blinka_focuser_28byj_16 is focuser_28byj_16
    assert blinka_focuser_a4988_nema17_full is focuser_a4988_nema17_full
    assert blinka_focuser_a4988_nema17_half is focuser_a4988_nema17_half
    assert serial_focuser_28byj_64 is FocuserSerial28byj_64
    assert motorkit_focuser_single_step is FocuserMotorKitSingleStep
