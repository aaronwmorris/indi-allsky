import time
import logging

from .fanBase import FanBase


logger = logging.getLogger('indi_allsky')


class FanDockerPi4ChannelRelay_I2C(FanBase):
    def __init__(self, *args, **kwargs):
        super(FanDockerPi4ChannelRelay_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']
        #pin_1_name = kwargs['pin_1_name']
        invert_output = kwargs['invert_output']

        import board
        #import busio
        from ..controllers import dockerpi

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.info('Initializing Docker Pi 4 Channel Relay I2C FAN control device @ %s', hex(i2c_address))

        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

        self.fan_controller = dockerpi.DockerPi4ChannelRelay(i2c, address=i2c_address)


        if not invert_output:
            self.ON = 1
            self.OFF = 0
        else:
            self.ON = 0
            self.OFF = 1


        self._state = None

        time.sleep(1.0)

