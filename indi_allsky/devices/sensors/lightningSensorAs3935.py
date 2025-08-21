import time
import logging

from .sensorBase import SensorBase
from ... import constants
#from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightningSensorAs3935(SensorBase):
    afemode_outdoor = True
    mask_disturbers = True
    noise_level = 2
    watchdog_threshold = 2
    spike_rejection = 2
    lightning_threshold = 1


    def update(self):
        strike_count = 3
        distance = 4

        logger.info('[%s] AS3935 - strikes: %d, distance: %d', self.name, strike_count, distance)

        data = {
            'data' : (
                strike_count,
                distance,
            ),
        }

        return data


class LightningSensorAs3935_I2C(LightningSensorAs3935):

    METADATA = {
        'name' : 'AS3935 (i2c)',
        'description' : 'AS3935 i2c Lightning Sensor',
        'count' : 2,
        'labels' : (
            'Stike Count',
            'Distance',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightningSensorAs3935_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import sparkfun_qwiicas3935

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] AS3935 I2C lightning sensor @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.as3935 = sparkfun_qwiicas3935.Sparkfun_QwiicAS3935_I2C(i2c)(i2c, address=i2c_address)


        time.sleep(1)  # allow things to settle


        if not self.as3935.connected:
            raise Exception('AS3935 is not connected, check wiring')


        if self.afemode_outdoor:
            self.as3935.indoor_outdoor = self.as3935.OUTDOOR
        else:
            self.as3935.indoor_outdoor = self.as3935.INDOOR

        self.as3935.mask_disturber = self.mask_disturber
        self.as3935.noise_level = self.noise_level
        self.as3935.watchdog_threshold = self.watchdog_threshold
        self.as3935.spike_rejection = self.spike_rejection
        self.as3935.lightning_threshold = self.lightning_threshold


class LightningSensorAs3935_SPI(LightningSensorAs3935):

    METADATA = {
        'name' : 'AS3935 (SPI)',
        'description' : 'AS3935 SPI Ligntning Sensor',
        'count' : 2,
        'labels' : (
            'Strike Count',
            'Distance',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightningSensorAs3935_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        #import busio
        import digitalio
        import sparkfun_qwiicas3935

        pin1 = getattr(board, pin_1_name)
        cs = digitalio.DigitalInOut(pin1)

        logger.warning('Initializing [%s] AS3935 SPI lightning sensor', self.name)
        spi = board.SPI()
        #spi = busio.SPI(board.SCLK, board.MOSI, board.MISO)
        self.as3935 = sparkfun_qwiicas3935.Sparkfun_QwiicAS3935_SPI(spi, cs)


        time.sleep(1)  # allow things to settle


        if not self.as3935.connected:
            raise Exception('AS3935 is not connected, check wiring')


        if self.afemode_outdoor:
            self.as3935.indoor_outdoor = self.as3935.OUTDOOR
        else:
            self.as3935.indoor_outdoor = self.as3935.INDOOR

        self.as3935.mask_disturber = self.mask_disturber
        self.as3935.noise_level = self.noise_level
        self.as3935.watchdog_threshold = self.watchdog_threshold
        self.as3935.spike_rejection = self.spike_rejection
        self.as3935.lightning_threshold = self.lightning_threshold
