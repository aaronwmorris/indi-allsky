from micropython import const
import adafruit_bus_device.i2c_device as i2cdevice


try:
    from busio import I2C
except ImportError:
    pass


class DockerPi4ChannelRelay(object):

    RELAY1 = const(0x01)
    RELAY2 = const(0x02)
    RELAY3 = const(0x03)
    RELAY4 = const(0x04)

    RELAY_OFF = const(0x00)
    RELAY_ON = const(0xFF)

    _relay_list = (RELAY1, RELAY2, RELAY3, RELAY4)
    _state_list = (RELAY_OFF, RELAY_ON)


    def __init__(self, i2c_bus: I2C, address: int = 0x10) -> None:
        self.i2c_device = i2cdevice.I2CDevice(i2c_bus, address)

        self._buffer = bytearray(2)


        self._relay_states = {
            self.RELAY1 : 0,
            self.RELAY2 : 0,
            self.RELAY3 : 0,
            self.RELAY4 : 0,
        }

        # set all relays off
        for relay in self._relay_list:
            self.set_relay(relay, False)


    def get_relay(self, relay):
        if relay not in self._relay_list:
            raise ValueError('Invalid relay')

        return self._relay_states[relay]


    def set_relay(self, relay, new_state):
        if relay not in self._relay_list:
            raise ValueError('Invalid relay')


        self._buffer[0] = relay

        if new_state:
            self._buffer[1] = self.RELAY_ON
        else:
            self._buffer[1] = self.RELAY_OFF


        with self.i2c_device as i2c:
            i2c.write(self._buffer, end=2)

        self._relay_states[relay] = int(new_state)
