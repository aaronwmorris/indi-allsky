import logging

from .sensorBase import SensorBase
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDs18x20(SensorBase):

    def __init__(self, *args, **kwargs):
        super(TempSensorDs18x20, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        from adafruit_onewire.bus import OneWireBus
        from adafruit_ds18x20 import DS18X20

        pin1 = getattr(board, pin_1_name)

        ow_bus = OneWireBus(pin1)

        logger.warning('Initializing DS18x20 temperature device')
        self.ds18x20 = DS18X20(ow_bus, ow_bus.scan()[0])

        ### 9, 10, 11, or 12
        self.ds18x20.resolution = 12


    def update(self):

        try:
            temp_c = float(self.ds18x20.temperature)
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
            'data' : (current_temp, ),
        }

        return data

