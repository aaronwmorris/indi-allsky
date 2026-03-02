#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException
from ..exceptions import DeviceControlException


logger = logging.getLogger('indi_allsky')


class VocSensorSgp40(SensorBase):

    def update(self):

        try:
            gas_raw = int(self.sgp.raw)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SGP40 - Gas: %d', self.name, gas_raw)


        data = {
            'data' : (
                gas_raw,
            ),
        }

        return data


class VocSensorSgp40_I2C(VocSensorSgp40):

    METADATA = {
        'name' : 'SGP40 (i2c)',
        'description' : 'SGP40 i2c VOC Sensor',
        'count' : 1,
        'labels' : (
            'Gas (Raw)',
        ),
        'types' : (
            constants.SENSOR_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(VocSensorSgp40_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_sgp40

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SGP40 I2C VOC sensor device @ %s', self.name, hex(i2c_address))

        try:
            i2c = board.I2C()
            #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
            #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
            self.sgp = adafruit_sgp40.SGP40(i2c, address=i2c_address)
        except Exception as e:
            logger.error('Device init exception: %s', str(e))
            raise DeviceControlException from e

