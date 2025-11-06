import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBmp280(SensorBase):

    def update(self):

        try:
            temp_c = float(self.bmp280.temperature)
            pressure_hpa = float(self.bmp280.pressure)  # hPa
            #altitude = float(self.bmp280.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] BMP280 - temp: %0.1fc, pressure: %0.1fhPa', self.name, temp_c, pressure_hpa)


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


class TempSensorBmp280_I2C(TempSensorBmp280):

    METADATA = {
        'name' : 'BMP280 (i2c)',
        'description' : 'BMP280 i2c Temperature Sensor',
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
        super(TempSensorBmp280_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        #import busio
        import adafruit_bmp280

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] BMP280 I2C temperature device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        #i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        #i2c = busio.I2C(board.D1, board.D0, frequency=100000)  # Raspberry Pi i2c bus 0 (pins 28/27)
        self.bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=i2c_address)


        self.bmp280.overscan_temperature = adafruit_bmp280.OVERSCAN_X1
        self.bmp280.overscan_pressure = adafruit_bmp280.OVERSCAN_X16
        self.bmp280.iir_filter = adafruit_bmp280.IIR_FILTER_DISABLE


        # throw away
        self.bmp280.temperature
        self.bmp280.pressure

        time.sleep(1)  # allow things to settle


class TempSensorBmp280_SPI(TempSensorBmp280):

    METADATA = {
        'name' : 'BMP280 (SPI)',
        'description' : 'BMP280 SPI Temperature Sensor',
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
        super(TempSensorBmp280_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        #import busio
        import digitalio
        import adafruit_bmp280

        pin1 = getattr(board, pin_1_name)
        cs = digitalio.DigitalInOut(pin1)

        logger.warning('Initializing [%s] BMP280 SPI temperature device', self.name)
        spi = board.SPI()
        #spi = busio.SPI(board.SCLK, board.MOSI, board.MISO)
        self.bmp280 = adafruit_bmp280.Adafruit_BMP280_SPI(spi, cs)


        self.bmp280.overscan_temperature = adafruit_bmp280.OVERSCAN_X1
        self.bmp280.overscan_pressure = adafruit_bmp280.OVERSCAN_X16
        self.bmp280.iir_filter = adafruit_bmp280.IIR_FILTER_DISABLE


        # throw away
        self.bmp280.temperature
        self.bmp280.pressure

        time.sleep(1)  # allow things to settle

