#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class CurrentSensorIna260(SensorBase):

    def update(self):

        try:
            current_mA = float(self.ina260.current)  # current in mA
            voltage = float(self.ina260.voltage)
            power_mw = float(self.ina260.power)  # power in milli-watts
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        current_A = current_mA / 1000
        power_w = power_mw / 1000


        logger.info(
            'INA260 - %0.2fV, %0.3fA, %0.3fW',
            voltage,
            current_A,
            power_w,
        )


        data = {
            'data' : (
                voltage,
                current_A,
                power_w,
            ),
        }

        return data


class CurrentSensorIna260_I2C(CurrentSensorIna260):

    METADATA = {
        'name' : 'INA260 (i2c)',
        'description' : 'INA260 i2c Current Sensor',
        'count' : 3,
        'labels' : (
            'Voltage (V)',
            'Current (A)',
            'Power (W)',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(CurrentSensorIna260_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']


        import board
        #import busio
        from adafruit_ina260 import INA260
        #from adafruit_ina260 import Mode
        #from adafruit_ina260 import AveragingCount
        #from adafruit_ina260 import ConversionTime

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] INA260 I2C current sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.ina260 = INA260(i2c, address=i2c_address)


        #self.ina260.mode = Mode.CONTINUOUS
        #self.ina260.averaging_count = AveragingCount.COUNT_4
        #self.ina260.current_conversion_time = ConversionTime.TIME_1_1_ms

