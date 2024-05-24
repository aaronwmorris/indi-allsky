import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDht22(TempSensorBase):
    dht_classname = 'DHT22'

    def __init__(self, *args, **kwargs):
        super(TempSensorDht22, self).__init__(*args, **kwargs)

        import board
        import adafruit_dht

        pin1 = getattr(board, self.config.get('TEMP_SENSOR', {}).get('PIN_1', 'notdefined'))

        logger.warning('Initializing %s temperature device', self.dht_classname)
        dht_class = getattr(adafruit_dht, self.dht_classname)
        self.dht = dht_class(pin1, use_pulseio=False)


    def update(self):

        try:
            temp_c = float(self.dht.temperature)
            rel_h = float(self.dht.humidity)
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        dew_point_c = self.get_dew_point_c(temp_c, rel_h)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = ((temp_c * 9.0 ) / 5.0) + 32
            current_dp = ((dew_point_c * 9.0 ) / 5.0) + 32
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = temp_c + 273.15
            current_dp = dew_point_c + 273.15
        else:
            current_temp = temp_c
            current_dp = dew_point_c


        logger.info('Temperature device: temp %0.1f, humidity %0.1f%%', current_temp, rel_h)

        data = {
            'dew_point' : current_dp,
            'data' : (current_temp, rel_h),
        }

        return data


class TempSensorDht11(TempSensorDht22):
    dht_classname = 'DHT11'

