import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorMlx90615(SensorBase):

    def update(self):

        try:
            temp_c = float(self.mlx.ambient_temperature)
            object_temp_c = float(self.mlx.object_temperature)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] MLX90615 - ambient temp: %0.1fc, object temp: %0.1fc', self.name, temp_c, object_temp_c)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
            object_temp = self.c2f(object_temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            object_temp = self.c2k(object_temp_c)
        else:
            current_temp = temp_c
            object_temp = object_temp_c


        data = {
            'data' : (
                current_temp,
                object_temp,
            ),
        }

        return data


class TempSensorMlx90615_I2C(TempSensorMlx90615):

    METADATA = {
        'name' : 'MLX90615 (i2c)',
        'description' : 'MLX90615 i2c Sky Temperature Sensor',
        'count' : 2,
        'labels' : (
            'Temperature',
            'Sky Temperature',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorMlx90615_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        from . import adafruit_mlx90615

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] MLX90615 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.mlx = adafruit_mlx90615.MLX90615(i2c, address=i2c_address)
