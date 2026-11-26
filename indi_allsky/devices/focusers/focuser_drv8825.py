import time
import logging

from .focuserBase import FocuserBase

from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class focuser_drv8825(FocuserBase):
    """DRV8825 / Step-Dir-Enable stepper focuser driver (3 GPIO pins: STEP, DIR, EN)."""

    STEP_DELAY = 0.002

    def __init__(self, *args, **kwargs):
        super(focuser_drv8825, self).__init__(*args, **kwargs)

        import board
        import digitalio

        pin_names = kwargs['pin_names']

        pin1 = getattr(board, pin_names[0])
        pin2 = getattr(board, pin_names[1])
        pin3 = getattr(board, pin_names[2])

        try:
            self.pins = {
                'step': digitalio.DigitalInOut(pin1),
                'dir': digitalio.DigitalInOut(pin2),
                'en': digitalio.DigitalInOut(pin3),
            }

            for pin in self.pins.values():
                pin.direction = digitalio.Direction.OUTPUT

            # Active-low enable: keep driver disabled at rest to prevent motor heating
            self.pins['en'].value = 1
        except Exception as e:  # catch all exceptions, not raspberry pi specific
            logger.error('GPIO exception: %s', str(e))
            raise DeviceControlException from e

    def move(self, direction, degrees):
        steps = round(degrees / (360 / self.STEPS))

        self.step(direction, steps)

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        return steps

    def step(self, direction, steps):
        self.pins['dir'].value = 1 if direction == 'cw' else 0

        self.pins['en'].value = 0
        try:
            for _ in range(steps):
                self.pins['step'].value = 1
                time.sleep(self.STEP_DELAY)
                self.pins['step'].value = 0
                time.sleep(self.STEP_DELAY)
        finally:
            self.pins['en'].value = 1

    def deinit(self):
        super(focuser_drv8825, self).deinit()

        if 'en' in self.pins:
            self.pins['en'].value = 1

        for pin in self.pins.values():
            pin.deinit()


class focuser_drv8825_28byj_full(focuser_drv8825):
    # 28BYJ-48 in bipolar mode, full-step carrier setting
    STEPS = 2048


class focuser_drv8825_28byj_half(focuser_drv8825):
    # 28BYJ-48 in bipolar mode, 1/2-step carrier setting
    STEPS = 4096


class focuser_drv8825_nema17_full(focuser_drv8825):
    # NEMA17 1.8 degrees per step, full-step carrier setting
    STEPS = 200


class focuser_drv8825_nema17_half(focuser_drv8825):
    # NEMA17 0.9 degrees per step, 1/2-step carrier setting
    STEPS = 400
