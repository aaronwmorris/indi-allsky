import time
import logging

from .dewHeaterBase import DewHeaterBase


logger = logging.getLogger('indi_allsky')


class DewHeaterDockerPi4ChannelRelay_I2C(DewHeaterBase):
    def __init__(self, *args, **kwargs):
        super(DewHeaterDockerPi4ChannelRelay_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']
        pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        #import busio
        from ..controllers import dockerpi

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.info('Initializing Docker Pi 4 Channel Relay I2C Dew Heater control device @ %s', hex(i2c_address))

        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

        self.dh_controller = dockerpi.DockerPi4ChannelRelay(i2c, address=i2c_address)
        self.relay = getattr(dockerpi.DockerPi4ChannelRelay, pin_1_name)


        if not invert_output:
            self.ON = 1
            self.OFF = 0
        else:
            self.ON = 0
            self.OFF = 1


        self._state = None

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set dew heater state: 100%')
            self.dh_controller.set_relay(self.relay, self.ON)
            self._state = 100
        else:
            logger.warning('Set dew heater state: 0%')
            self.dh_controller.set_relay(self.relay, self.OFF)
            self._state = 0


    def disable(self):
        self.state = 0


