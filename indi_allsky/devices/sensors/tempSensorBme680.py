import time
import logging

from .sensorBase import SensorBase
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempSensorBme680(SensorBase):

    def update(self):

        try:
            temp_c = float(self.bme680.temperature)
            rel_h = float(self.bme680.humidity)
            pressure_hpa = float(self.bme680.pressure)  # hPa
            gas_ohm = float(self.bme680.gas)  # ohm
            #altitude = float(self.bme680.altitude)  # meters
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('BME680 - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa, gas: %0.1f', temp_c, rel_h, pressure_hpa, gas_ohm)

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
            'data' : (current_temp, rel_h, current_pressure, gas_ohm),
        }

        return data


class TempSensorBme680_I2C(TempSensorBme680):

    def __init__(self, *args, **kwargs):
        super(TempSensorBme680_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_bme680

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing BME680 I2C temperature device @ %s', hex(i2c_address))
        i2c = board.I2C()
        self.bme680 = adafruit_bme680.Adafruit_BME680_I2C(i2c, address=i2c_address)


class TempSensorBme680_SPI(TempSensorBme680):

    def __init__(self, *args, **kwargs):
        super(TempSensorBme680_SPI, self).__init__(*args, **kwargs)

        pin_1_name = kwargs['pin_1_name']

        import board
        import digitalio
        import adafruit_bme680

        pin1 = getattr(board, pin_1_name)
        cs = digitalio.DigitalInOut(pin1)

        logger.warning('Initializing BME680 SPI temperature device')
        spi = board.SPI()
        self.bme680 = adafruit_bme680.Adafruit_BME680_SPI(spi, cs)


        # throw away, initial humidity reading is always 100%
        self.bme680.temperature
        self.bme680.humidity
        self.bme680.pressure
        self.bme680.gas

        time.sleep(2)  # allow things to settle

