import logging
import smbus

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException

logger = logging.getLogger('indi_allsky')


class UpsHatWaveshareE_MCU_I2C(SensorBase):
    """
    Waveshare UPS HAT (E) MCU reader (I2C addr 0x2D).
    Liefert Batterie-/VBUS-/Zellwerte als Slots (floats).
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
            # Wenn du alle 4 Zellen willst: count=14 und unten Cell3/Cell4 ergänzen
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
        self.i2c_address = int(i2c_address_str, 16)  # config liefert string
        self.bus = smbus.SMBus(1)

        logger.warning('Initializing [%s] Waveshare UPS HAT (E) MCU @ %s', self.name, hex(self.i2c_address))


    def _u16(self, lo, hi):
        return (lo | (hi << 8))


    def _s16(self, lo, hi):
        v = self._u16(lo, hi)
        if v & 0x8000:
            v -= 0x10000
        return v


    def update(self):
        try:
            # Status @ 0x02
            st = self.bus.read_i2c_block_data(self.i2c_address, 0x02, 0x01)[0]
            if st & self.BIT_FAST:
                state = 3.0
            elif st & self.BIT_CHG:
                state = 2.0
            elif st & self.BIT_DIS:
                state = 1.0
            else:
                state = 0.0

            # VBUS @ 0x10 (6 bytes): mV, mA, mW (u16)
            d = self.bus.read_i2c_block_data(self.i2c_address, 0x10, 0x06)
            vbus_mv = float(self._u16(d[0], d[1]))
            vbus_ma = float(self._u16(d[2], d[3]))
            vbus_mw = float(self._u16(d[4], d[5]))

            # Battery @ 0x20 (12 bytes)
            d = self.bus.read_i2c_block_data(self.i2c_address, 0x20, 0x0C)
            bat_mv  = float(self._u16(d[0], d[1]))
            bat_ma  = float(self._s16(d[2], d[3]))   # signed!
            bat_pct = float(self._u16(d[4], d[5]))
            rem_mah = float(self._u16(d[6], d[7]))
            tte_min = float(self._u16(d[8], d[9]))
            ttf_min = float(self._u16(d[10], d[11]))

            # Cells @ 0x30 (8 bytes) – hier nur Cell1+Cell2 als Beispiel
            d = self.bus.read_i2c_block_data(self.i2c_address, 0x30, 0x08)
            c1 = float(self._u16(d[0], d[1]))
            c2 = float(self._u16(d[2], d[3]))
            c3 = float(self._u16(d[4], d[5]))
            c4 = float(self._u16(d[6], d[7]))

        except OSError as e:
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
