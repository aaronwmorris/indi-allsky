import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDht22(TempSensorBase):
    dht_classname = 'DHT22'

    def __init__(self, *args, **kwargs):
        super(TempSensorDht11, self).__init__(*args, **kwargs)

        import board
        import Adafruit_DHT

        pin1 = getattr(board, self.config.get('TEMP_SENSOR', {}).get('PIN_1', 'notdefined'))

        dht_class = getattr(Adafruit_DHT, self.dht_classname)
        self.dht = dht_class(pin1, use_pulseio=False)


    def update(self):

        try:
            temp_c = self.dht.temperature
            humidity = self.dht.humidity
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = ((temp_c.current * 9.0 ) / 5.0) + 32
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = temp_c.current + 273.15
        else:
            current_temp = float(temp_c.current)


        return (current_temp, humidity)


class TempSensorDht11(TempSensorDht22):
    dht_classname = 'DHT11'

