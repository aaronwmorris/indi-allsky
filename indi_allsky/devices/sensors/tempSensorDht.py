import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorDht2x(SensorBase):

    def update(self):

        try:
            temp_c = float(self.dht.temperature)
            rel_h = float(self.dht.humidity)
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] DHT - temp: %0.1fc, humidity: %0.1f%%', self.name, temp_c, rel_h)


        try:
            dew_point_c = self.get_dew_point_c(temp_c, rel_h)
            frost_point_c = self.get_frost_point_c(temp_c, dew_point_c)
        except ValueError as e:
            logger.error('Dew Point calculation error - ValueError: %s', str(e))
            dew_point_c = 0.0
            frost_point_c = 0.0


        heat_index_c = self.get_heat_index_c(temp_c, rel_h)


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
            current_dp = self.c2f(dew_point_c)
            current_fp = self.c2f(frost_point_c)
            current_hi = self.c2f(heat_index_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
            current_dp = self.c2k(dew_point_c)
            current_fp = self.c2k(frost_point_c)
            current_hi = self.c2k(heat_index_c)
        else:
            current_temp = temp_c
            current_dp = dew_point_c
            current_fp = frost_point_c
            current_hi = heat_index_c


        data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'data' : (
                current_temp,
                rel_h,
                current_dp,
            ),
        }

        return data


class TempSensorDht22(TempSensorDht2x):

    METADATA = {
        'name' : 'DHT22',
        'description' : 'DHT22/AM2302 Temperature Sensor',
        'count' : 3,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorDht2x, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import adafruit_dht

        pin1 = getattr(board, pin_1_name)

        logger.warning('Initializing [%s] DHT22 temperature device', self.name)
        self.dht = adafruit_dht.DHT22(pin1, use_pulseio=False)


class TempSensorDht21(TempSensorDht2x):

    METADATA = {
        'name' : 'DHT21',
        'description' : 'DHT21/AM2301 Temperature Sensor',
        'count' : 3,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorDht2x, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import adafruit_dht

        pin1 = getattr(board, pin_1_name)

        logger.warning('Initializing [%s] DHT21 temperature device', self.name)
        self.dht = adafruit_dht.DHT21(pin1, use_pulseio=False)


class TempSensorDht11(TempSensorDht2x):

    METADATA = {
        'name' : 'DHT11',
        'description' : 'DHT11 Temperature Sensor',
        'count' : 3,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorDht2x, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import adafruit_dht

        pin1 = getattr(board, pin_1_name)

        logger.warning('Initializing [%s] DHT11 temperature device', self.name)
        self.dht = adafruit_dht.DHT11(pin1, use_pulseio=False)

