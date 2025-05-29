import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorMlx90640(SensorBase):

    SENSOR_WIDTH = 32
    SENSOR_HEIGHT = 24


    def update(self):
        import numpy

        frame = [0] * self.SENSOR_WIDTH * self.SENSOR_HEIGHT
        try:
            self.mlx.getFrame(frame)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        data = list()
        for x in range(self.SENSOR_HEIGHT):
            data.append(frame[x * self.SENSOR_WIDTH:x * self.SENSOR_WIDTH + self.SENSOR_WIDTH])

        image_f = numpy.array(data)
        object_temp_avg_c = numpy.mean(image_f)

        logger.info('[%s] MLX90640 - average object temp: %0.1fc', self.name, object_temp_avg_c)


        #import cv2
        #image_u16 = (image_f * 10).astype(numpy.uint16)  # remap to 0.1 degree increments
        #data_min = image_u16.min()
        #data_max = image_u16.max()
        #logger.info('Min: %d, Max: %d', data_min, data_max)
        #image_u16[image_u16 < data_min] = data_min  # clip
        #image_u16[image_u16 > data_max] = data_max

        #image_remapped = (((image_u16 - data_min) / (data_max - data_min)) * 255).astype(numpy.uint8)
        #image_heat = cv2.applyColorMap(image_remapped, cv2.COLORMAP_JET)

        #scale_factor = 8
        #image_heat = cv2.resize(image_heat, (self.SENSOR_WIDTH * scale_factor, self.SENSOR_HEIGHT * scale_factor), cv2.INTER_LINEAR)
        #cv2.imwrite('/var/www/html/allsky/images/mlx90640.jpg', image_heat, [cv2.IMWRITE_JPEG_QUALITY, 90])


        if self.config.get('TEMP_DISPLAY') == 'f':
            object_temp_avg = self.c2f(object_temp_avg_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            object_temp_avg = self.c2k(object_temp_avg_c)
        else:
            object_temp_avg = object_temp_avg_c


        data = {
            'data' : (
                object_temp_avg,
            ),
        }

        return data


class TempSensorMlx90640_I2C(TempSensorMlx90640):

    METADATA = {
        'name' : 'MLX90640 (i2c)',
        'description' : 'MLX90640 i2c Thermal Camera',
        'count' : 1,
        'labels' : (
            'Sky Temperature',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorMlx90640_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_mlx90640

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] MLX90640 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.mlx = adafruit_mlx90640.MLX90640(i2c, address=i2c_address)

        self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_1_HZ

