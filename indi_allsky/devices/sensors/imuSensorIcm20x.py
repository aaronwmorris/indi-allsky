#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class ImuSensorIcm20x(SensorBase):

    def update(self):

        try:
            mag_x, mag_y, mag_z = self.icm.magnetic
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] ICM20X - Magnetometer X:%0.2f, Y:%0.2f, Z:%0.2f uTf', self.name, mag_x, mag_y, mag_z)


        data = {
            'data' : (
                mag_x,
                mag_y,
                mag_z,
            ),
        }

        return data


class ImuSensorIcm20x_I2C(ImuSensorIcm20x):

    METADATA = {
        'name' : 'ICM20X (i2c)',
        'description' : 'ICM20X i2c IMU Sensor',
        'count' : 3,
        'labels' : (
            'Mag X',
            'Mag Y',
            'Mag Z',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(ImuSensorIcm20x_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_icm20x

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] ICM20x I2C IMU sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.icm = adafruit_icm20x.ICM20948(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e

