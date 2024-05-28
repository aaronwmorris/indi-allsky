import logging

from .tempSensorBase import TempSensorBase
from ..exceptions import TemperatureReadException


logger = logging.getLogger('indi_allsky')


class TempSensorSi7021(TempSensorBase):

    def update(self):

        try:
            temp_c = float(self.si7021.temperature)
            rel_h = float(self.si7021.relative_humidity)
        except RuntimeError as e:
            raise TemperatureReadException(str(e)) from e


        logger.info('Si7021 - temp: %0.1fc, humidity: %0.1f%%', temp_c, rel_h)


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


class TempSensorSi7021_I2C(TempSensorSi7021):

    def __init__(self, *args, **kwargs):
        super(TempSensorSi7021_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_si7021

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing Si7021 I2C temperature device @ %s', hex(i2c_address))
        i2c = board.I2C()
        self.si7021 = adafruit_si7021.SI7021(i2c, address=i2c_address)


        ### If you'd like to use the heater, you can uncomment the code below
        ### and pick a heater level that works for your purposes
        #self.si7021.heater_enable = True
        #self.si7021.heater_level = 0  # Use any level from 0 to 15 inclusive


        # The heater level of the integrated resistive heating element.  Per
        # the data sheet, the levels correspond to the following current draws:

        # ============  =================
        # Heater Level  Current Draw (mA)
        # ============  =================
        # 0             3.09
        # 1             9.18
        # 2             15.24
        # .             .
        # 4             27.39
        # .             .
        # 8             51.69
        # .             .
        # 15            94.20
        # ============  =================


