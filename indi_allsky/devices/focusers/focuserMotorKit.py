import time
import logging

from .focuserBase import FocuserBase
from ..exceptions import DeviceControlException

logger = logging.getLogger('indi_allsky')


class FocuserMotorKitBase(FocuserBase):

    STEP_FACTOR = 1.0

    STEPS_PER_TURN = 360  # one step is one "degree"
    CAN_STOP = True


    def __init__(self, *args, **kwargs):
        super(FocuserMotorKitBase, self).__init__(*args, **kwargs)

        import board
        #import busio
        from adafruit_motorkit import MotorKit

        pin_names = kwargs['pin_names']
        i2c_address_str = kwargs['i2c_address']


        i2c_address = int(i2c_address_str, 16)  # string in config

        # pin 1 should be the name for the motor/stepper
        stepper_name = str(pin_names[0])


        logger.warning('Initializing MotorKit I2C focuser %s device @ %s', stepper_name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)

        kit = MotorKit(i2c=i2c, address=i2c_address)

        self.stepper = getattr(kit, stepper_name)


    @property
    def STEPS_PER_SECOND(self):
        # 20 onesteps per second (0.05 s each), STEP_FACTOR onesteps per step
        return 20 / self.STEP_FACTOR


    def move(self, direction, degrees):
        steps = degrees  # assumptions are being made

        if direction == 'ccw':
            steps *= -1  # negative for CCW

        return self.move_steps(steps)


    def move_steps(self, steps, should_stop=None):
        from adafruit_motor import stepper


        steps = int(steps)

        if steps >= 0:
            stepper_dir = stepper.FORWARD
            sign = 1
        else:
            stepper_dir = stepper.BACKWARD
            sign = -1


        style = self.getStepStyle()


        # Not sure if this is necessary
        #self.stepper.release()

        moved = 0
        onesteps_done = 0
        try:
            for i in range(1, abs(steps) + 1):
                # a step is one degree, STEP_FACTOR onesteps (can be fractional)
                onesteps_due = int(i * self.STEP_FACTOR)

                while onesteps_done < onesteps_due:
                    self.stepper.onestep(direction=stepper_dir, style=style)
                    time.sleep(0.05)
                    onesteps_done += 1

                moved += sign

                if should_stop is not None and should_stop():
                    break
        except RuntimeError as e:
            raise DeviceControlException(str(e)) from e
        finally:
            self.stepper.release()

        return moved


    def getStepStyle(self):
        raise NotImplementedError('Override in subclass')


class FocuserMotorKitSingleStep(FocuserMotorKitBase):

    STEP_FACTOR = 1.0

    def getStepStyle(self):
        from adafruit_motor import stepper
        return stepper.SINGLE


class FocuserMotorKitDoubleStep(FocuserMotorKitBase):

    STEP_FACTOR = 0.5

    def getStepStyle(self):
        from adafruit_motor import stepper
        return stepper.DOUBLE


class FocuserMotorKitInterleaveStep(FocuserMotorKitBase):

    STEP_FACTOR = 2.0

    def getStepStyle(self):
        from adafruit_motor import stepper
        return stepper.INTERLEAVE


class FocuserMotorKitMicrostepStep(FocuserMotorKitBase):

    STEP_FACTOR = 4.0

    def getStepStyle(self):
        from adafruit_motor import stepper
        return stepper.MICROSTEP
