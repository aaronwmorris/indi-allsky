import io
from pathlib import Path
import logging

from .sensorBase import SensorBase
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDs18x20(SensorBase):

    def __init__(self, *args, **kwargs):
        super(TempSensorDs18x20, self).__init__(*args, **kwargs)

        logger.warning('Initializing DS18x20 temperature device')


        w1_base_dir = Path('/sys/bus/w1/devices/')

        if not w1_base_dir.is_dir():
            raise Exception('1-Wire interface is not enabled')


        # Get all folders beginning with 28
        device_folders = list(w1_base_dir.glob('28*'))


        if len(device_folders) == 0:
            raise Exception('DS18x20 device not found')
        if len(device_folders) > 1:
            logger.warning('Multiple DS18x20 devices detected')


        # multiple devices might be available, we only want one
        self.ds_temp_file = device_folders[0].joinpath('temperature')


        if not self.ds_temp_file.is_file():
            raise Exception('DS18x20 temperature property not found')


    def update(self):

        with io.open(self.ds_temp_file, 'r') as f_temp:
            temp_str = f_temp.readline().rstrip()


        try:
            temp_c = int(temp_str) / 1000.0
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('DS18x20 - temp: %0.1fc', temp_c)


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

