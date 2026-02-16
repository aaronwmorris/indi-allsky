#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class CurrentSensorIna228(SensorBase):

    def update(self):

        try:
            bus_voltage = float(self.ina228.bus_voltage)  # voltage on V- (load side)
            shunt_voltage = float(self.ina228.shunt_voltage)  # voltage between V+ and V- across the shunt
            current_mA = float(self.ina228.current)  # current in mA
            power_mW = float(self.ina228.power)  # power in watts
            temp_c = float(self.ina228.die_temperature)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        current_A = current_mA / 1000
        power_w = power_mW / 1000


        # not sure if this is necessary
        #voltage = bus_voltage + shunt_voltage


        logger.info(
            'INA228 - %0.2fV, %0.3fA, %0.3fW - Shunt %0.2fmV - Temp: %0.1fc',
            bus_voltage,
            current_A,
            power_w,
            shunt_voltage * 1000,
            temp_c,
        )


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c



        data = {
            'data' : (
                bus_voltage,
                current_A,
                power_w,
                current_temp,
            ),
        }

        return data


class CurrentSensorIna228_I2C(CurrentSensorIna228):

    METADATA = {
        'name' : 'INA228 (i2c)',
        'description' : 'INA228 i2c Current Sensor',
        'count' : 4,
        'labels' : (
            'Voltage (V)',
            'Current (A)',
            'Power (W)',
            'Die Temperature',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(CurrentSensorIna228_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']


        import board
        #import busio
        from adafruit_ina228 import INA228

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] INA228 I2C current sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.ina228 = INA228(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e


