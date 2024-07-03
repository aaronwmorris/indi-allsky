from pathlib import Path
import time
import logging

from .dewHeaterBase import DewHeaterBase
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class DewHeaterSerialPwm(DewHeaterBase):

    BAUD_RATE = 9600


    def __init__(self, *args, **kwargs):
        super(DewHeaterSerialPwm, self).__init__(*args, **kwargs)

        serial_port_name = kwargs['pin_1_name']

        logger.info('Initializing serial controlled DEW HEATER device')

        self.serial_port = Path('/dev').joinpath(serial_port_name)

        if not self.serial_port.exists():
            raise DeviceControlException('Serial port does not exist: {0:s}'.format(str(self.serial_port)))


        self._state = None

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        import serial

        # duty cycle must be a percentage between 0 and 100
        new_state_i = int(new_state)

        if new_state_i < 0:
            logger.error('Duty cycle must be 0 or greater')
            return

        if new_state_i > 100:
            logger.error('Duty cycle must be 100 or less')
            return


        logger.warning('Set dew heater state: %d%%', new_state_i)

        try:
            self.send_serial_dew_heater(new_state)
        except serial.SerialException as e:
            raise DeviceControlException(str(e)) from e


        self._state = new_state_i


    def disable(self):
        self.state = 0


    def send_serial_dew_heater(self, duty_cycle):
        import serial

        with serial.Serial(str(self.serial_port), self.BAUD_RATE, timeout=1) as ser:
            ser.write(('H' + str(duty_cycle) + '\n').encode())

