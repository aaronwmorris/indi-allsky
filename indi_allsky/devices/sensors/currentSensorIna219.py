#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class CurrentSensorIna219(SensorBase):

    def update(self):

        try:
            bus_voltage = float(self.ina219.bus_voltage)  # voltage on V- (load side)
            shunt_voltage = float(self.ina219.shunt_voltage)  # voltage between V+ and V- across the shunt
            current_mA = float(self.ina219.current)  # current in mA
            power_w = float(self.ina219.power)  # power in watts
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        # INA219 measures bus voltage on the load side. PSU voltage = bus_voltage + shunt_voltage
        voltage = bus_voltage + shunt_voltage

        current_A = current_mA / 1000


        logger.info(
            'INA219 - %0.2fV, %0.3fA, %0.3fW - Shunt %0.2fmV',
            voltage,
            current_A,
            power_w,
            shunt_voltage * 1000,
        )


        data = {
            'data' : (
                voltage,
                current_A,
                power_w,
            ),
        }

        return data


class CurrentSensorIna219_I2C(CurrentSensorIna219):

    METADATA = {
        'name' : 'INA219 (i2c)',
        'description' : 'INA219 i2c Current Sensor',
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
        super(CurrentSensorIna219_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']


        import board
        #import busio
        from adafruit_ina219 import INA219
        from adafruit_ina219 import ADCResolution
        from adafruit_ina219 import BusVoltageRange

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] INA219 I2C current sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.ina219 = INA219(i2c, addr=i2c_address)


        # change configuration to use 32 samples averaging for both bus voltage and shunt voltage
        self.ina219.bus_adc_resolution = ADCResolution.ADCRES_12BIT_32S
        self.ina219.shunt_adc_resolution = ADCResolution.ADCRES_12BIT_32S

        # change voltage range to 16V
        self.ina219.bus_voltage_range = BusVoltageRange.RANGE_16V

