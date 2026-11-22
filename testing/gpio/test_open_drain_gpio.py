import sys
import types
import unittest
from unittest.mock import patch

from indi_allsky.devices import dew_heaters, fans, generic
from indi_allsky.devices.dew_heaters.dewHeaterOpenDrain import DewHeaterOpenDrain
from indi_allsky.devices.fans.fanOpenDrain import FanOpenDrain
from indi_allsky.devices.generic.gpioOpenDrain import GpioOpenDrain
from indi_allsky.flask.forms import IndiAllskyConfigForm


class _FakeDigitalInOut:
    def __init__(self, pin):
        self.pin = pin
        self.calls = []
        self.deinit_called = False

    def switch_to_output(self, value=False):
        self.calls.append(('output', value))

    def switch_to_input(self, pull=None):
        self.calls.append(('input', pull))

    def deinit(self):
        self.deinit_called = True


class TestOpenDrainDevices(unittest.TestCase):

    def _mock_blinka(self):
        fake_board = types.SimpleNamespace(D13='PIN_D13', D21='PIN_D21')
        fake_digitalio = types.SimpleNamespace(DigitalInOut=_FakeDigitalInOut)
        return patch.dict(sys.modules, {'board': fake_board, 'digitalio': fake_digitalio})

    def test_open_drain_normal_polarity(self):
        cases = (
            (GpioOpenDrain, 1, 0),
            (FanOpenDrain, 100, 0),
            (DewHeaterOpenDrain, 100, 0),
        )
        with self._mock_blinka(), patch('indi_allsky.devices.openDrainMixin.time.sleep'):
            for cls, on_val, off_val in cases:
                dev = cls({}, pin_1_name='D13', invert_output=False)
                self.assertEqual(dev.pin.calls, [('input', None)])

                dev.state = 1
                self.assertEqual(dev.state, on_val)
                self.assertEqual(dev.pin.calls[-1], ('output', False))

                dev.disable()
                self.assertEqual(dev.state, off_val)
                self.assertEqual(dev.pin.calls[-1], ('input', None))

                dev.deinit()
                self.assertTrue(dev.pin.deinit_called)

    def test_open_drain_inverted_polarity(self):
        with self._mock_blinka(), patch('indi_allsky.devices.openDrainMixin.time.sleep'):
            dev = GpioOpenDrain({}, pin_1_name='D21', invert_output=True)
            self.assertEqual(dev.pin.calls, [('output', False)])

            dev.state = 1
            self.assertEqual(dev.state, 1)
            self.assertEqual(dev.pin.calls[-1], ('input', None))

            dev.state = 0
            self.assertEqual(dev.state, 0)
            self.assertEqual(dev.pin.calls[-1], ('output', False))

    def test_exports_and_form_choices(self):
        self.assertIs(generic.blinka_gpio_open_drain, GpioOpenDrain)
        self.assertIs(fans.blinka_fan_open_drain, FanOpenDrain)
        self.assertIs(dew_heaters.blinka_dew_heater_open_drain, DewHeaterOpenDrain)

        self.assertIn('blinka_gpio_open_drain', dict(IndiAllskyConfigForm.GENERIC_GPIO__CLASSNAME_choices))
        self.assertIn('blinka_fan_open_drain', dict(IndiAllskyConfigForm.FAN__CLASSNAME_choices))
        self.assertIn('blinka_dew_heater_open_drain', dict(IndiAllskyConfigForm.DEW_HEATER__CLASSNAME_choices))


if __name__ == '__main__':
    unittest.main()
