import time
import logging

from .focuserBase import FocuserBase
from ..exceptions import DeviceControlException

logger = logging.getLogger('indi_allsky')


class FocuserMotorKitBase(FocuserBase):

    STEP_FACTOR = 1.0


    def __init__(self, *args, **kwargs):
        super(FocuserMotorKitBase, self).__init__(*args, **kwargs)

        import board
        #import busio
        from adafruit_motorkit import MotorKit

        pin_names = kwargs['pin_names']
        i2c_address_str = kwargs['i2c_address']


        i2c_address = int(i2c_address_str, 16)  # string in config

        # pin 1 should be an number for the motor
        motor_name = 'motor{0:d}'.format(int(pin_names[0]))


        logger.warning('Initializing MotorKit %s I2C focuser device @ %s', motor_name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)

        kit = MotorKit(i2c=i2c, address=i2c_address)

        self.stepper = getattr(kit, motor_name)


    def move(self, direction, degrees):
        from adafruit_motor import stepper


        steps = degrees  # assumptions are being made
        stepper_dir = stepper.FORWARD


        if direction == 'ccw':
            steps *= -1  # negative for CCW
            stepper_dir = stepper.BACKWARD


        style = self.getStepStyle()


        # Not sure if this is necessary
        #self.stepper.release()

        try:
            for _ in range(int(steps * self.STEP_FACTOR)):
                self.stepper.onestep(direction=stepper_dir, style=style)
                time.sleep(0.05)

            self.stepper.release()
        except RuntimeError as e:
            raise DeviceControlException(str(e)) from e


        self.stepper.release()

        return steps


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
