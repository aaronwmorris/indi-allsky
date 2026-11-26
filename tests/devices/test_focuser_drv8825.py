import sys
import types
import unittest
from unittest.mock import patch


class _FakePin:
    def __init__(self, pin_id):
        self.pin_id = pin_id
        self.direction = None
        self.history = []
        self._value = None
        self.deinited = False

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, val):
        self._value = val
        self.history.append(val)

    def deinit(self):
        self.deinited = True


class TestFocuserDrv8825(unittest.TestCase):
    def _make_mocks(self):
        fake_board = types.SimpleNamespace(D6='D6', D5='D5', D12='D12')
        fake_digitalio = types.SimpleNamespace(
            DigitalInOut=_FakePin,
            Direction=types.SimpleNamespace(OUTPUT='OUTPUT'),
        )
        return {'board': fake_board, 'digitalio': fake_digitalio}

    def test_28byj_half_step_en_lifecycle_and_steps(self):
        from indi_allsky.devices.focusers import blinka_focuser_drv8825_28byj_half

        with patch.dict(sys.modules, self._make_mocks()):
            with patch('indi_allsky.devices.focusers.focuser_drv8825.time.sleep'):
                focuser = blinka_focuser_drv8825_28byj_half({}, pin_names=['D6', 'D5', 'D12'])

                # Disabled at rest after init
                self.assertEqual(focuser.pins['en'].value, 1)

                steps_moved = focuser.move('cw', 90)
                self.assertEqual(steps_moved, 1024)
                self.assertEqual(focuser.pins['dir'].value, 1)
                self.assertEqual(focuser.pins['en'].history, [1, 0, 1])
                self.assertEqual(focuser.pins['en'].value, 1)
                self.assertEqual(len(focuser.pins['step'].history), 2048)

                ccw_steps = focuser.move('ccw', 90)
                self.assertEqual(ccw_steps, -1024)
                self.assertEqual(focuser.pins['dir'].value, 0)
                self.assertEqual(focuser.pins['en'].value, 1)

                focuser.deinit()
                self.assertTrue(all(p.deinited for p in focuser.pins.values()))

    def test_28byj_full_and_nema17_step_counts(self):
        from indi_allsky.devices.focusers import (
            blinka_focuser_drv8825_28byj_full,
            blinka_focuser_drv8825_nema17_full,
            blinka_focuser_drv8825_nema17_half,
        )

        with patch.dict(sys.modules, self._make_mocks()):
            with patch('indi_allsky.devices.focusers.focuser_drv8825.time.sleep'):
                f_28_full = blinka_focuser_drv8825_28byj_full({}, pin_names=['D6', 'D5', 'D12'])
                self.assertEqual(f_28_full.move('cw', 180), 1024)

                f_nema_full = blinka_focuser_drv8825_nema17_full({}, pin_names=['D6', 'D5', 'D12'])
                self.assertEqual(f_nema_full.move('cw', 180), 100)

                f_nema_half = blinka_focuser_drv8825_nema17_half({}, pin_names=['D6', 'D5', 'D12'])
                self.assertEqual(f_nema_half.move('cw', 180), 200)


if __name__ == '__main__':
    unittest.main()
