#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class MagSensorMmc5983maSF(SensorBase):

    def update(self):

        try:
            x, y, z = self.mag.get_measurement_xyz_gauss()
            x = float(x)
            y = float(y)
            z = float(z)

            temp_c = float(self.mag.get_temperature())
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] MMC5983MA - X: %0.4f, Y: %0.4f, Z: %0.4f', self.name, x, y, z)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        data = {
            'data' : (
                x,
                y,
                z,
                current_temp,
            ),
        }

        return data


class MagSensorMmc5983maSF_I2C(MagSensorMmc5983maSF):

    METADATA = {
        'name' : 'MMC5983MA (i2c)',
        'description' : 'MMC5983MA Magnetometer Sensor',
        'count' : 4,
        'labels' : (
            'X Gauss',
            'Y Gauss',
            'Z Gauss',
            'Temperature',
        ),
        'types' : (
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_MISC,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(MagSensorMmc5983maSF_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import qwiic_mmc5983ma

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] MMC5983MA I2C magnetometer sensor device @ %s', self.name, hex(i2c_address))
        self.mag = qwiic_mmc5983ma.QwiicMMC5983MA(address=i2c_address)


        if self.mag.is_connected() is False:
            logger.error('MMC5983MA is not connected')
            raise Exception('MMC5983MA is not connected')


        # Initialize the device
        self.mag.begin()
