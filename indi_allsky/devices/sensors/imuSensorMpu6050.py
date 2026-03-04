#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class ImuSensorMpu6050(SensorBase):

    def update(self):
        try:
            temp_c = float(self.mpu.temperature)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] MPU6050 - Temp: %0.2fc', self.name, temp_c)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        data = {
            'data' : (
                current_temp,
            ),
        }


        return data


class ImuSensorMpu6050_I2C(ImuSensorMpu6050):

    METADATA = {
        'name' : 'MPU6050(i2c)',
        'description' : 'MPU6050 i2c IMU Sensor',
        'count' : 1,
        'labels' : (
            'Temperature',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(ImuSensorMpu6050_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_mpu6050

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] MPU6050 I2C IMU sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.mpu = adafruit_mpu6050.MPU6050(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e

