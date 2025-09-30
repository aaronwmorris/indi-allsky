from adafruit_bus_device import i2c_device
from micropython import const

try:
    from busio import I2C
except ImportError:
    pass

# imports

__version__ = "1.0.0"

# Internal constants:
_MLX90615_I2CADDR = const(0x5B)

_MLX90615_TA = const(0x26)
_MLX90615_TOBJ1 = const(0x27)


class MLX90615:

    def __init__(self, i2c_bus: I2C, address: int = _MLX90615_I2CADDR) -> None:
        self._device = i2c_device.I2CDevice(i2c_bus, address)
        self.buf = bytearray(2)


    @property
    def ambient_temperature(self) -> float:
        """Ambient Temperature in Celsius."""
        return self._read_temp(_MLX90615_TA)


    @property
    def object_temperature(self) -> float:
        """Object Temperature in Celsius."""
        return self._read_temp(_MLX90615_TOBJ1)


    def _read_temp(self, register: int) -> float:
        temp = self._read_16(register)
        temp *= 0.02
        temp -= 273.15
        return temp


    def _read_16(self, register: int) -> int:
        # Read and return a 16-bit unsigned big endian value read from the
        # specified 16-bit register address.
        with self._device as i2c:
            self.buf[0] = register
            i2c.write_then_readinto(self.buf, self.buf, out_end=1)
            return self.buf[1] << 8 | self.buf[0]
