import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class UpsHatWaveshareE_MCU_I2C(SensorBase):
    """Waveshare UPS HAT (E) MCU reader (I2C addr 0x2D).

    Waveshare UPS HAT (E) MCU reader (I2C addr 0x2D).
    Liefert Batterie-/VBUS-/Zellwerte als Slots (floats).

    WICHTIG: Verwende CircuitPython/Blinka I2C (board.I2C + I2CDevice) statt smbus,
    damit mehrere Module/Devices im selben Prozess denselben I2C-Bus teilen können
    (Singleton/Locking über Blinka/Adafruit BusDevice).
    """


    METADATA = {
        'name' : 'Waveshare UPS HAT (E) MCU (i2c)',
        'description' : 'Waveshare UPS HAT (E) MCU @ 0x2D (Battery/VBUS/Cells)',
        'count' : 14,
        'labels' : (
            'State (0=idle,1=disch,2=chg,3=fast)',
            'VBUS Voltage (mV)',
            'VBUS Current (mA)',
            'VBUS Power (mW)',
            'Battery Voltage (mV)',
            'Battery Current (mA, signed)',
            'Battery Percent (%)',
            'Remaining Capacity (mAh)',
            'Time to Empty (min)',
            'Time to Full (min)',
            'Cell1 Voltage (mV)',
            'Cell2 Voltage (mV)',
            'Cell3 Voltage (mV)',
            'Cell4 Voltage (mV)',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    DEFAULT_ADDR = 0x2D
    BIT_FAST = 0x40
    BIT_CHG  = 0x80
    BIT_DIS  = 0x20


    def __init__(self, *args, **kwargs):
        super(UpsHatWaveshareE_MCU_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs.get('i2c_address', '0x2d')
        i2c_address = int(i2c_address_str, 16)  # config liefert string

        # Defer imports so environments without Blinka don't break module import.
        import board
        import adafruit_bus_device.i2c_device as i2cdevice

        logger.warning('Initializing [%s] Waveshare UPS HAT (E) MCU @ %s', self.name, hex(i2c_address))


        try:
            # board.I2C() is shared/singleton-like under Blinka and supports locking.
            i2c = board.I2C()
            # i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)  # optional alternative
            self._device = i2cdevice.I2CDevice(i2c, i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


        # Reusable buffers to avoid allocations on each update()
        self._reg_buf = bytearray(1)
        self._buf_status = bytearray(1)
        self._buf_vbus = bytearray(6)
        self._buf_bat = bytearray(12)
        self._buf_cells = bytearray(8)


    def _u16(self, lo, hi):
        return (lo | (hi << 8))


    def _s16(self, lo, hi):
        v = self._u16(lo, hi)
        if v & 0x8000:
            v -= 0x10000
        return v


    def _read_into(self, register, buf):
        """Read `len(buf)` bytes from `register` into `buf`."""
        self._reg_buf[0] = register
        with self._device as i2c:
            # Write one-byte register pointer, then read into buffer.
            i2c.write_then_readinto(self._reg_buf, buf, out_end=1)


    def update(self):
        try:
            # Status @ 0x02
            self._read_into(0x02, self._buf_status)
            st = self._buf_status[0]
            if st & self.BIT_FAST:
                state = 3.0
            elif st & self.BIT_CHG:
                state = 2.0
            elif st & self.BIT_DIS:
                state = 1.0
            else:
                state = 0.0

            # VBUS @ 0x10 (6 bytes): mV, mA, mW (u16)
            self._read_into(0x10, self._buf_vbus)
            d = self._buf_vbus
            vbus_mv = float(self._u16(d[0], d[1]))
            vbus_ma = float(self._u16(d[2], d[3]))
            vbus_mw = float(self._u16(d[4], d[5]))

            # Battery @ 0x20 (12 bytes)
            self._read_into(0x20, self._buf_bat)
            d = self._buf_bat
            bat_mv  = float(self._u16(d[0], d[1]))
            bat_ma  = float(self._s16(d[2], d[3]))   # signed!
            bat_pct = float(self._u16(d[4], d[5]))
            rem_mah = float(self._u16(d[6], d[7]))
            tte_min = float(self._u16(d[8], d[9]))
            ttf_min = float(self._u16(d[10], d[11]))

            # Cells @ 0x30 (8 bytes)
            self._read_into(0x30, self._buf_cells)
            d = self._buf_cells
            c1 = float(self._u16(d[0], d[1]))
            c2 = float(self._u16(d[2], d[3]))
            c3 = float(self._u16(d[4], d[5]))
            c4 = float(self._u16(d[6], d[7]))

        except (OSError, RuntimeError, ValueError) as e:
            raise SensorReadException(str(e)) from e


        logger.info(
            'UPS HAT(E) MCU - state=%s vbus=%smV/%smA/%smW bat=%smV/%smA %s%% rem=%smAh',
            state, vbus_mv, vbus_ma, vbus_mw, bat_mv, bat_ma, bat_pct, rem_mah
        )


        return {
            'data' : (
                state,
                vbus_mv,
                vbus_ma,
                vbus_mw,
                bat_mv,
                bat_ma,
                bat_pct,
                rem_mah,
                tte_min,
                ttf_min,
                c1,
                c2,
                c3,
                c4,
            ),
        }
