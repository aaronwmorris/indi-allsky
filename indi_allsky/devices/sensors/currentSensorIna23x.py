#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class CurrentSensorIna23x(SensorBase):

    def update(self):

        try:
            bus_voltage = float(self.ina23x.bus_voltage)  # voltage on V- (load side)
            shunt_voltage = float(self.ina23x.shunt_voltage)  # voltage between V+ and V- across the shunt
            current_A = float(self.ina23x.current)  # current in mA
            power_w = float(self.ina23x.power)  # power in watts
            temp_c = float(self.ina23x.die_temperature)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        # not sure if this is necessary
        #voltage = bus_voltage + shunt_voltage


        logger.info(
            'INA23x - %0.2fV, %0.3fA, %0.3fW - Shunt %0.2fmV - Temp: %0.1fc',
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


class CurrentSensorIna23x_I2C(CurrentSensorIna23x):

    METADATA = {
        'name' : 'INA23x (i2c)',
        'description' : 'INA23x i2c Current Sensor',
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
        super(CurrentSensorIna23x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']


        import board
        #import busio
        from adafruit_ina23x import INA23X

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] INA23x I2C current sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.ina23x = INA23X(i2c, address=i2c_address)


