#import time
import math
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class CurrentSensorIna3221(SensorBase):

    def update(self):

        # set all values to 0
        current_data = [0.0 for x in range(self.METADATA.count)]


        try:
            for channel_idx in self.ina3221_channels:
                voltage, current_a, power_w = self.getChannel(channel_idx)

                current_data[0 + (3 * channel_idx)] = voltage
                current_data[1 + (3 * channel_idx)] = current_a
                current_data[2 + (3 * channel_idx)] = power_w
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e



        data = {
            'data' : current_data,
        }

        return data


    def getChannel(self, channel_idx):
        shunt_voltage = float(self.ina3221[channel_idx].shunt_voltage)


        if math.isnan(shunt_voltage):
            logger.error('INA3221 Channel %d shunt voltage is undefined', channel_idx + 1)
            return -1.0, -1.0, -1.0


        ### note: not sure if the shunt voltage needs to be added to the bus voltage

        bus_voltage = float(self.ina3221[channel_idx].bus_voltage)
        current_mA = float(self.ina3221[channel_idx].current)

        current_a = current_mA * 1000
        power_w = bus_voltage * current_a

        logger.info(
            'INA3221 Channel %d: %0.2fV, %0.3fA, %0.3fW - Shunt %0.2fmV',
            channel_idx + 1,
            bus_voltage,
            current_a,
            power_w,
            shunt_voltage,
        )

        return bus_voltage, current_a, power_w


class CurrentSensorIna3221_I2C(CurrentSensorIna3221):

    METADATA = {
        'name' : 'INA3221 (i2c)',
        'description' : 'INA3221 i2c Current Sensor',
        'count' : 9,
        'labels' : (
            'Channel 1 Voltage (V)',
            'Channel 1 Current (A)',
            'Channel 1 Power (W)',
            'Channel 2 Voltage (V)',
            'Channel 2 Current (A)',
            'Channel 2 Power (W)',
            'Channel 3 Voltage (V)',
            'Channel 3 Current (A)',
            'Channel 3 Power (W)',
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
        ),
    }


    def __init__(self, *args, **kwargs):
        super(CurrentSensorIna3221_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']


        self.ina3221_channels = list()
        if self.config.get('TEMP_SENSOR', {}).get('INA3221_CH1_ENABLE', True):
            self.ina3221_channels.append(0)

        if self.config.get('TEMP_SENSOR', {}).get('INA3221_CH2_ENABLE', True):
            self.ina3221_channels.append(1)

        if self.config.get('TEMP_SENSOR', {}).get('INA3221_CH3_ENABLE', True):
            self.ina3221_channels.append(2)


        import board
        #import busio
        from adafruit_ina3221 import INA3221

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] INA3221 I2C current sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.ina3221 = INA3221(i2c, address=i2c_address, enable=self.ina3221_channels)

