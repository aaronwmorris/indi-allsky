import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBme280(SensorBase):

    def update(self):

        try:
            temp_c = float(self.bme280.temperature)
            rel_h = float(self.bme280.humidity)
            pressure_hpa = float(self.bme280.pressure)  # hPa
            #altitude = float(self.bme280.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] BME280 - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa', self.name, temp_c, rel_h, pressure_hpa)

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


        if self.config.get('PRESSURE_DISPLAY') == 'psi':
            current_pressure = self.hPa2psi(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'inHg':
            current_pressure = self.hPa2inHg(pressure_hpa)
        elif self.config.get('PRESSURE_DISPLAY') == 'mmHg':
            current_pressure = self.hPa2mmHg(pressure_hpa)
        else:
            current_pressure = pressure_hpa


        data = {
            'dew_point' : current_dp,
            'frost_point' : current_fp,
            'heat_index' : current_hi,
            'data' : (
                current_temp,
                rel_h,
                current_pressure,
                current_dp,
            ),
        }

        return data


class TempSensorBme280_I2C(TempSensorBme280):

    METADATA = {
        'name' : 'BME280 (i2c)',
        'description' : 'BME280 i2c Temperature Sensor',
        'count' : 4,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Pressure',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
            constants.SENSOR_TEMPERATURE,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(TempSensorBme280_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        from adafruit_bme280 import advanced as adafruit_bme280

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] BME280 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.bme280 = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=i2c_address)


        self.bme280.overscan_humidity = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_temperature = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_pressure = adafruit_bme280.OVERSCAN_X16
        self.bme280.iir_filter = adafruit_bme280.IIR_FILTER_DISABLE


        # throw away
        self.bme280.temperature
        self.bme280.humidity
        self.bme280.pressure

        time.sleep(1)  # allow things to settle


class TempSensorBme280_SPI(TempSensorBme280):

    METADATA = {
        'name' : 'BME280 (SPI)',
        'description' : 'BME280 SPI Temperature Sensor',
        'count' : 4,
        'labels' : (
            'Temperature',
            'Relative Humidity',
            'Pressure',
            'Dew Point',
        ),
        'types' : (
            constants.SENSOR_TEMPERATURE,
            constants.SENSOR_RELATIVE_HUMIDITY,
            constants.SENSOR_ATMOSPHERIC_PRESSURE,
            constants.SENSOR_TEMPERATURE,
        ),
    }

    def __init__(self, *args, **kwargs):
        super(TempSensorBme280_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import digitalio
        from adafruit_bme280 import advanced as adafruit_bme280

        pin1 = getattr(board, pin_1_name)
        cs = digitalio.DigitalInOut(pin1)

        logger.warning('Initializing [%s] BME280 SPI temperature device', self.name)
        spi = board.SPI()
        self.bme280 = adafruit_bme280.Adafruit_BME280_SPI(spi, cs)


        self.bme280.overscan_humidity = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_temperature = adafruit_bme280.OVERSCAN_X1
        self.bme280.overscan_pressure = adafruit_bme280.OVERSCAN_X16
        self.bme280.iir_filter = adafruit_bme280.IIR_FILTER_DISABLE


        # throw away
        self.bme280.temperature
        self.bme280.humidity
        self.bme280.pressure

        time.sleep(1)  # allow things to settle

