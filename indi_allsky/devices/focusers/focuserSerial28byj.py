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


    def __init__(self, *args, **kwargs):
        super(FocuserSerial28byj, self).__init__(*args, **kwargs)

        pin_names = kwargs['pin_names']

        serial_port_name = pin_names[0]

        self.serial_port = Path('/dev').joinpath(serial_port_name)

        if not self.serial_port.exists():
            raise DeviceControlException('Serial port does not exist: {0:s}'.format(str(self.serial_port)))


    def move(self, direction, degrees):
        import serial

        steps = self.STEP_DEGREES[degrees]


        if direction == 'ccw':
            steps *= -1  # negative for CCW


        try:
            self.send_serial_stepper(steps)
        except serial.SerialException as e:
            raise DeviceControlException(str(e)) from e


        # need to give the stepper a chance to move
        time.sleep((abs(degrees) / 10))


        return steps


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

