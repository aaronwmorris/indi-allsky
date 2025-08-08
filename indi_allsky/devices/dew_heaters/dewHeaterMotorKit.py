import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterMotorKitPwm(DewHeaterBase):

    def __init__(self, *args, **kwargs):
        super(DewHeaterMotorKitPwm, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']
        pin_1_name = kwargs['pin_1_name']
        self.invert_output = kwargs['invert_output']


        import board
        #import busio
        from adafruit_motorkit import MotorKit


        i2c_address = int(i2c_address_str, 16)  # string in config
        motor_name = 'motor{0:d}'.format(int(pin_1_name))

        logger.info('Initializing MotorKit DEW HEATER device %s @ %s', motor_name, i2c_address_str)

        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        kit = MotorKit(i2c=i2c, address=i2c_address)

        self.motor = getattr(kit, motor_name)

        self._state = 0

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # duty cycle must be a percentage between 0 and 100
        new_state_i = int(new_state)

        if new_state_i < 0:
            logger.error('Duty cycle must be 0 or greater')
            return

        if new_state_i > 100:
            logger.error('Duty cycle must be 100 or less')
            return


        if not self.invert_output:
            new_duty_cycle = new_state_i / 100
        else:
            new_duty_cycle = (100 - new_state_i) / 100


        logger.warning('Set dew heater state: %d%%', new_state_i)
        self.motor.throttle = new_duty_cycle

        self._state = new_state_i


    def disable(self):
        self.state = 0


    def deinit(self):
        super(DewHeaterMotorKitPwm, self).deinit()

