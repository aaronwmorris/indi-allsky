import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBmp180(SensorBase):

    def update(self):

        try:
            temp_c = float(self.bmp180.temperature)
            pressure_hpa = float(self.bmp180.pressure)  # hPa
            #altitude = float(self.bmp180.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] BMP180 - temp: %0.1fc, pressure: %0.1fhPa', self.name, temp_c, pressure_hpa)

        # no humidity sensor


        if self.config.get('TEMP_DISPLAY') == 'f':
            current_temp = self.c2f(temp_c)
        elif self.config.get('TEMP_DISPLAY') == 'k':
            current_temp = self.c2k(temp_c)
        else:
            current_temp = temp_c


        if self.config.get('PRESSURE_DISPLAY') == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'data' : (
                current_temp,
                current_pressure,
            ),
        }

        return data


class TempSensorBmp180_I2C(TempSensorBmp180):

    METADATA = {
        'name' : 'BMP180 (i2c)',
        'description' : 'BMP180 i2c Temperature Sensor',
        'count' : 2,
        'labels' : (
            'Temperature',
            'Pressure',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorBmp180_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import bmp180

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] BMP180 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.bmp180 = bmp180.BMP180(i2c, address=i2c_address)

