#import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorSi1145(SensorBase):

    def update(self):

        try:
            vis, ir = self.si1145.als
            uv_index = self.si1145.uv_index
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        try:
            vis = int(vis)
            ir = int(ir)
            uv_index = float(uv_index)
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SI1145 - visible: %d, ir: %d, uv: %0.3f', self.name, vis, ir, uv_index)


        data = {
            'data' : (
                vis,
                ir,
                uv_index,
            ),
        }

        return data


class LightSensorSi1145_I2C(LightSensorSi1145):

    METADATA = {
        'name' : 'SI1145 (i2c)',
        'description' : 'SI1145 i2c Light Sensor',
        'count' : 3,
        'labels' : (
            'Visible',
            'IR',
            'UV Index',
        ),
        'types' : (
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorSi1145_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_si1145

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SI1145 I2C light sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.si1145 = adafruit_si1145.SI1145(i2c, address=i2c_address)


        # enable UV index
        self.si1145.uv_index_enabled = True

