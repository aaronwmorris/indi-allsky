import time
import logging

from .exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class OpenDrainPinMixin(object):
    """Emulate open-drain output via digitalio direction switching.

    ON sinks current (OUTPUT driven LOW); OFF releases the line to high
    impedance (INPUT). Note: ensure the host GPIO pin tolerates the external
    pull-up voltage when floating.
    """

    def _init_open_drain_pin(self, pin_1_name, invert_output, device_label):
        import board
        import digitalio

        logger.info('Initializing open-drain %s device: %s', device_label, str(pin_1_name))

        pin1 = getattr(board, pin_1_name)

        try:
            self.pin = digitalio.DigitalInOut(pin1)
            self._invert_open_drain = bool(invert_output)
            if self._invert_open_drain:
                logger.warning('%s open-drain logic reversed', device_label)
            self._set_open_drain_state(False)
        except Exception as e:  # catch all exceptions, not raspberry pi specific
            logger.error('GPIO exception: %s', str(e))
            raise DeviceControlException from e

        time.sleep(1.0)

    def _set_open_drain_state(self, active):
        sink = (not active) if self._invert_open_drain else bool(active)
        if sink:
            self.pin.switch_to_output(value=False)
        else:
            self.pin.switch_to_input()

    def disable(self):
        self.state = 0

    def deinit(self):
        super(OpenDrainPinMixin, self).deinit()
        self.pin.deinit()
