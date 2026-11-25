"""move_steps on every focuser driver, with the hardware libraries faked."""
from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

from indi_allsky.devices.focusers import focuserSimulator
from indi_allsky.devices.focusers import focuserSerial28byj
from indi_allsky.devices.focusers.focuser_28byj import focuser_28byj_16, focuser_28byj_64
from indi_allsky.devices.focusers.focuser_a4988 import focuser_a4988_nema17_full, focuser_a4988_nema17_half
from indi_allsky.devices.focusers.focuserBase import FocuserBase
from indi_allsky.devices.focusers.focuserMotorKit import (
    FocuserMotorKitDoubleStep,
    FocuserMotorKitInterleaveStep,
    FocuserMotorKitMicrostepStep,
    FocuserMotorKitSingleStep,
)


class FakePin:
    def __init__(self, name):
        self.name = name
        self.direction = None
        self.log = []
        self._value = 0

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
        self.log.append(v)

    def deinit(self):
        pass


class Recorder:
    """Counts should_stop calls and stops after a chosen number of them."""

    def __init__(self, stop_after=None):
        self.calls = 0
        self.stop_after = stop_after

    def __call__(self):
        self.calls += 1
        return self.stop_after is not None and self.calls >= self.stop_after


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    sleep = mock.Mock()
    monkeypatch.setattr('time.sleep', sleep)
    return sleep


@pytest.fixture
def gpio(monkeypatch):
    board = types.SimpleNamespace(D1='D1', D2='D2', D3='D3', D4='D4')
    digitalio = types.SimpleNamespace(
        DigitalInOut=lambda p: FakePin(p),
        Direction=types.SimpleNamespace(OUTPUT='out'),
    )
    monkeypatch.setitem(sys.modules, 'board', board)
    monkeypatch.setitem(sys.modules, 'digitalio', digitalio)


PINS = ['D1', 'D2', 'D3', 'D4']


def make_28byj(cls):
    return cls({}, pin_names=PINS)


def coil_states(f):
    """Every coil state written, in order (one tuple per set_step)."""
    n = len(f.pins[0].log)
    return [tuple(p.log[i] for p in f.pins) for i in range(n)]


# ---- 28BYJ ----

@pytest.mark.parametrize('cls, per_turn', [(focuser_28byj_64, 512), (focuser_28byj_16, 128)])
def test_28byj_constants(gpio, cls, per_turn):
    f = make_28byj(cls)
    assert (f.STEPS_PER_TURN, f.STEPS_PER_SECOND, f.CAN_STOP) == (per_turn, 25, True)


def test_28byj_outward_steps_count_and_sign(gpio):
    f = make_28byj(focuser_28byj_64)
    rec = Recorder()
    assert f.move_steps(5, rec) == 5
    assert rec.calls == 5
    states = coil_states(f)
    # reset, 5 x 8 SEQ entries, reset
    assert len(states) == 2 + 40
    assert states[0] == states[-1] == (0, 0, 0, 0)
    # cw walks SEQ backwards
    assert states[1:9] == list(focuser_28byj_64.SEQ[::-1])


def test_28byj_inward_walks_seq_forwards(gpio):
    f = make_28byj(focuser_28byj_64)
    assert f.move_steps(-3) == -3
    assert coil_states(f)[1:9] == list(focuser_28byj_64.SEQ)


def test_28byj_stops_early_and_releases_coils(gpio):
    f = make_28byj(focuser_28byj_64)
    rec = Recorder(stop_after=3)
    assert f.move_steps(10, rec) == 3
    assert rec.calls == 3
    assert coil_states(f)[-1] == (0, 0, 0, 0)
    rec = Recorder(stop_after=2)
    assert f.move_steps(-10, rec) == -2


def test_28byj_should_stop_after_the_last_step_too(gpio):
    f = make_28byj(focuser_28byj_64)
    rec = Recorder()
    f.move_steps(1, rec)
    assert rec.calls == 1


def test_28byj_move_unchanged(gpio):
    f = make_28byj(focuser_28byj_64)
    assert f.move('cw', 180) == 256
    cw = coil_states(f)
    assert len(cw) == 2 + 256 * 8
    assert cw[1:9] == list(focuser_28byj_64.SEQ[::-1])

    g = make_28byj(focuser_28byj_64)
    assert g.move('ccw', 45) == -64
    assert coil_states(g)[1:9] == list(focuser_28byj_64.SEQ)

    h = make_28byj(focuser_28byj_16)
    assert h.move('cw', 24) == 9


# ---- A4988 ----

@pytest.mark.parametrize('cls, per_turn', [(focuser_a4988_nema17_full, 200), (focuser_a4988_nema17_half, 400)])
def test_a4988_constants(gpio, cls, per_turn):
    f = cls({}, pin_names=PINS)
    assert (f.STEPS_PER_TURN, f.STEPS_PER_SECOND, f.CAN_STOP) == (per_turn, 100, True)


def test_a4988_steps_and_direction(gpio):
    f = focuser_a4988_nema17_full({}, pin_names=PINS)
    rec = Recorder()
    f.pins['step'].log.clear()
    assert f.move_steps(4, rec) == 4
    assert rec.calls == 4
    assert f.pins['dir'].value == 1
    assert f.pins['step'].log == [1, 0] * 4

    f.pins['step'].log.clear()
    assert f.move_steps(-2) == -2
    assert f.pins['dir'].value == 0
    assert f.pins['step'].log == [1, 0] * 2


def test_a4988_stops_early(gpio):
    f = focuser_a4988_nema17_half({}, pin_names=PINS)
    f.pins['step'].log.clear()
    rec = Recorder(stop_after=3)
    assert f.move_steps(50, rec) == 3
    assert rec.calls == 3
    assert f.pins['step'].log == [1, 0] * 3
    assert f.move_steps(-50, Recorder(stop_after=1)) == -1


def test_a4988_move_unchanged(gpio):
    f = focuser_a4988_nema17_full({}, pin_names=PINS)
    f.pins['step'].log.clear()
    assert f.move('cw', 90) == 50
    assert f.pins['dir'].value == 1
    assert f.pins['step'].log == [1, 0] * 50

    g = focuser_a4988_nema17_half({}, pin_names=PINS)
    g.pins['step'].log.clear()
    assert g.move('ccw', 45) == -50
    assert g.pins['dir'].value == 0
    assert g.pins['step'].log == [1, 0] * 50


# ---- MotorKit ----

@pytest.fixture
def motorkit(monkeypatch):
    stepper = mock.Mock()
    kit = types.SimpleNamespace(stepper1=stepper)
    stepper_consts = types.SimpleNamespace(
        FORWARD='fwd', BACKWARD='back', SINGLE='single', DOUBLE='double',
        INTERLEAVE='interleave', MICROSTEP='microstep',
    )
    monkeypatch.setitem(sys.modules, 'board', types.SimpleNamespace(I2C=lambda: object()))
    monkeypatch.setitem(sys.modules, 'adafruit_motorkit', types.SimpleNamespace(MotorKit=lambda **kw: kit))
    pkg = types.ModuleType('adafruit_motor')
    pkg.stepper = stepper_consts
    monkeypatch.setitem(sys.modules, 'adafruit_motor', pkg)
    monkeypatch.setitem(sys.modules, 'adafruit_motor.stepper', stepper_consts)
    return stepper


def make_kit(cls):
    return cls({}, pin_names=['stepper1'], i2c_address='0x60')


@pytest.mark.parametrize('cls, factor', [
    (FocuserMotorKitSingleStep, 1.0),
    (FocuserMotorKitDoubleStep, 0.5),
    (FocuserMotorKitInterleaveStep, 2.0),
    (FocuserMotorKitMicrostepStep, 4.0),
])
def test_motorkit_constants_and_onesteps(motorkit, cls, factor):
    f = make_kit(cls)
    assert f.STEPS_PER_TURN == 360
    assert f.CAN_STOP is True
    assert f.STEPS_PER_SECOND == pytest.approx(20 / factor)

    rec = Recorder()
    assert f.move_steps(10, rec) == 10
    assert rec.calls == 10
    assert motorkit.onestep.call_count == int(10 * factor)


def test_motorkit_inward_actually_steps(motorkit):
    f = make_kit(FocuserMotorKitSingleStep)
    assert f.move_steps(-7) == -7
    assert motorkit.onestep.call_count == 7
    assert all(c.kwargs['direction'] == 'back' for c in motorkit.onestep.call_args_list)
    assert motorkit.release.called


def test_motorkit_outward_is_forward(motorkit):
    f = make_kit(FocuserMotorKitSingleStep)
    f.move_steps(3)
    assert all(c.kwargs['direction'] == 'fwd' and c.kwargs['style'] == 'single'
               for c in motorkit.onestep.call_args_list)


def test_motorkit_stops_early(motorkit):
    f = make_kit(FocuserMotorKitInterleaveStep)
    rec = Recorder(stop_after=4)
    assert f.move_steps(-20, rec) == -4
    assert rec.calls == 4
    assert motorkit.onestep.call_count == 8
    assert motorkit.release.called


def test_motorkit_move_unchanged_and_inward_fixed(motorkit):
    f = make_kit(FocuserMotorKitSingleStep)
    assert f.move('cw', 6) == 6
    assert motorkit.onestep.call_count == 6
    motorkit.onestep.reset_mock()
    assert f.move('ccw', 6) == -6
    assert motorkit.onestep.call_count == 6  # was zero before the fix
    assert motorkit.onestep.call_args.kwargs['direction'] == 'back'


def test_motorkit_runtime_error_becomes_device_error(motorkit):
    from indi_allsky.devices.exceptions import DeviceControlException
    motorkit.onestep.side_effect = RuntimeError('i2c')
    f = make_kit(FocuserMotorKitSingleStep)
    with pytest.raises(DeviceControlException):
        f.move_steps(2)
    assert motorkit.release.called


# ---- Serial ----

@pytest.fixture
def serial_focuser(monkeypatch):
    monkeypatch.setitem(sys.modules, 'serial', types.SimpleNamespace(SerialException=OSError))
    monkeypatch.setattr(focuserSerial28byj.Path, 'exists', lambda self: True)
    f = focuserSerial28byj.FocuserSerial28byj_64({}, pin_names=['ttyACM0'])
    f.send_serial_stepper = mock.Mock()
    return f


def test_serial_constants(serial_focuser):
    f = serial_focuser
    assert (f.STEPS_PER_TURN, f.STEPS_PER_SECOND, f.CAN_STOP) == (512, 14, False)


def test_serial_move_steps_never_calls_should_stop(serial_focuser, fast):
    f = serial_focuser
    rec = Recorder(stop_after=1)
    assert f.move_steps(30, rec) == 30
    assert rec.calls == 0
    f.send_serial_stepper.assert_called_once_with(30)
    assert fast.call_args.args[0] == pytest.approx(30 / 14)

    f.send_serial_stepper.reset_mock()
    assert f.move_steps(-14, rec) == -14
    f.send_serial_stepper.assert_called_once_with(-14)

    f.send_serial_stepper.reset_mock()
    assert f.move_steps(0) == 0
    f.send_serial_stepper.assert_not_called()


def test_serial_move_unchanged(serial_focuser, fast):
    f = serial_focuser
    assert f.move('cw', 180) == 256
    f.send_serial_stepper.assert_called_with(256)
    assert fast.call_args.args[0] == 18
    assert f.move('ccw', 45) == -64
    f.send_serial_stepper.assert_called_with(-64)


# ---- Simulator ----

def test_simulator_constants_and_module_handle():
    focuserSimulator.FocuserSimulator({})
    b = focuserSimulator.FocuserSimulator({})
    assert focuserSimulator.SIMULATED_LENS is b
    assert (b.STEPS_PER_TURN, b.STEPS_PER_SECOND, b.CAN_STOP) == (512, 200, True)
    assert (b.position, b.backlash_steps, b.lens_position) == (0, 26, 0.0)


def test_simulator_counts_sleeps_and_stops(fast):
    s = focuserSimulator.FocuserSimulator({})
    rec = Recorder()
    assert s.move_steps(10, rec) == 10
    assert rec.calls == 10
    assert s.position == 10
    assert fast.call_count == 10
    assert fast.call_args.args[0] == pytest.approx(1 / 200)

    rec = Recorder(stop_after=4)
    assert s.move_steps(-100, rec) == -4
    assert s.position == 6


def test_simulator_outward_follows_at_once():
    s = focuserSimulator.FocuserSimulator({})
    s.move_steps(40)
    assert s.lens_position == 40.0


def test_simulator_backlash_after_reversal():
    s = focuserSimulator.FocuserSimulator({})
    s.move_steps(100)
    assert s.lens_position == 100.0

    s.move_steps(-26)  # takes up the backlash, the lens stays put
    assert s.position == 74
    assert s.lens_position == 100.0
    s.move_steps(-10)  # now it follows
    assert s.lens_position == 90.0

    s.move_steps(26)  # reversed again, backlash again
    assert s.lens_position == 90.0
    s.move_steps(5)
    assert s.lens_position == 95.0


def test_simulator_first_move_inward_has_backlash_too():
    s = focuserSimulator.FocuserSimulator({})
    s.move_steps(-26)
    assert s.lens_position == 0.0
    s.move_steps(-4)
    assert s.lens_position == -4.0


def test_simulator_move_unchanged(fast):
    s = focuserSimulator.FocuserSimulator({})
    assert s.move('cw', 45) == 45
    assert s.move('ccw', 45) == -45
    assert fast.call_args.args[0] == 1.0


def test_base_move_steps_not_implemented():
    with pytest.raises(NotImplementedError):
        FocuserBase({}).move_steps(1)
