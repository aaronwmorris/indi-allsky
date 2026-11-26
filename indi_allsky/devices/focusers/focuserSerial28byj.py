from pathlib import Path
import time
import logging

from .focuserBase import FocuserBase
from ..exceptions import DeviceControlException

logger = logging.getLogger('indi_allsky')


class FocuserSerial28byj(FocuserBase):

    BAUD_RATE = 9600

    # override in child class
    STEP_DEGREES = {}

    STEPS_PER_TURN = 512

    # 256 steps take 18 s
    STEPS_PER_SECOND = 14

    # a command cannot be interrupted once it is sent
    CAN_STOP = False


    def __init__(self, *args, **kwargs):
        super(FocuserSerial28byj, self).__init__(*args, **kwargs)

        pin_names = kwargs['pin_names']

        serial_port_name = pin_names[0]

        self.serial_port = Path('/dev').joinpath(serial_port_name)

        if not self.serial_port.exists():
            raise DeviceControlException('Serial port does not exist: {0:s}'.format(str(self.serial_port)))


    def move(self, direction, degrees):
        steps = self.STEP_DEGREES[degrees]


        if direction == 'ccw':
            steps *= -1  # negative for CCW


        self._send(steps)

        # need to give the stepper a chance to move
        time.sleep((abs(degrees) / 10))


        return steps


    def move_steps(self, steps, should_stop=None):
        # should_stop is never called, the command cannot be interrupted
        steps = int(steps)

        if steps == 0:
            return 0

        self._send(steps)

        # need to give the stepper a chance to move
        time.sleep(abs(steps) / self.STEPS_PER_SECOND)

        return steps


    def _send(self, steps):
        import serial

        try:
            self.send_serial_stepper(steps)
        except serial.SerialException as e:
            raise DeviceControlException(str(e)) from e


    def send_serial_stepper(self, steps):
        import serial

        with serial.Serial(str(self.serial_port), self.BAUD_RATE, timeout=1) as ser:
            ser.write(('S' + str(steps) + '\n').encode())


class FocuserSerial28byj_64(FocuserSerial28byj):
    # 1/64 ratio

    STEP_DEGREES = {
        6   : 8,
        12  : 17,
        24  : 34,
        45  : 64,
        90  : 128,
        180 : 256,
    }

