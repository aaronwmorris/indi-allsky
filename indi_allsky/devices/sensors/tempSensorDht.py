import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDht22(TempSensorBase):
    dht_classname = 'DHT22'

    def __init__(self, *args, **kwargs):
        super(TempSensorDht22, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import adafruit_dht

        pin1 = getattr(board, pin_1_name)

        logger.warning('Initializing %s temperature device', self.dht_classname)
        dht_class = getattr(adafruit_dht, self.dht_classname)
        self.dht = dht_class(pin1, use_pulseio=False)


    def update(self):

        try:
            temp_c = float(self.dht.temperature)
            rel_h = float(self.dht.humidity)
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        logger.info('%s - temp: %0.1fc, humidity: %0.1f%%', self.dht_classname, temp_c, rel_h)


        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0



        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c


        data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'data' : (current_temp, rel_h),
        }

        return data


class TempSensorDht21(TempSensorDht22):
    dht_classname = 'DHT21'


class TempSensorDht11(TempSensorDht22):
    dht_classname = 'DHT11'

