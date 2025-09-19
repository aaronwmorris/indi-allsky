import time
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanDockerPi4ChannelRelay_I2C(FanBase):
    def __init__(self, *args, **kwargs):
        super(FanDockerPi4ChannelRelay_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']
        pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        #import busio
        from ..controllers import dockerpi

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.info('Initializing Docker Pi 4 Channel Relay I2C FAN control device @ %s', hex(i2c_address))

        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

        self.fan_controller = dockerpi.DockerPi4ChannelRelay(i2c, address=i2c_address)
        self.relay = getattr(dockerpi.DockerPi4ChannelRelay, pin_1_name)


        if invert_output:
            logger.warning('Fan logic reversed')
            self.ON = 0
            self.OFF = 1
        else:
            self.ON = 1
            self.OFF = 0


        self._state = 0

        time.sleep(1.0)


    @property
    def state(self):
        return self._state


    @state.setter
    def state(self, new_state):
        # any positive value is ON
        new_state_b = bool(new_state)

        if new_state_b:
            logger.warning('Set fan state: 100%')
            self.fan_controller.set_relay(self.relay, self.ON)
            self._state = 100
        else:
            logger.warning('Set fan state: 0%')
            self.fan_controller.set_relay(self.relay, self.OFF)
            self._state = 0


    def disable(self):
        self.state = 0


