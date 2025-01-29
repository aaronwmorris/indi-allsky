import time
import logging

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class LightSensorSi1145(SensorBase):

    def update(self):
        if self.night != bool(self.night_v.value):
            self.night = bool(self.night_v.value)
            self.update_sensor_settings()


        #vis_gain = self.si1145.vis_gain
        #ir_gain = self.si1145.ir_gain
        #logger.info('[%s] SI1145 settings - Vis Gain: %d, IR Gain: %d', vis_gain, ir_gain)


        try:
            vis, ir = self.si1145.als
            uv_index = self.si1145.uv_index
        except RuntimeError as e:
            raise SensorReadException(str(e)) from e


        try:
            vis = int(vis)
            ir = int(ir)
            uv_index = float(uv_index)
        except TypeError as e:
            raise SensorReadException(str(e)) from e


        logger.info('[%s] SI1145 - visible: %d, ir: %d, uv: %0.3f', self.name, vis, ir, uv_index)


        data = {
            'data' : (
                vis,
                ir,
                uv_index,
            ),
        }

        return data


    def update_sensor_settings(self):
        if self.night:
            logger.info('[%s] Switching SI1145 to night mode - Visible Gain: %d, IR Gain: %d', self.name, self.vis_gain_night, self.ir_gain_night)
            self.si1145.vis_gain = self.vis_gain_night
            self.si1145.ir_gain = self.ir_gain_night
        else:
            logger.info('[%s] Switching SI1145 to day mode - Gain: %d, Integration: %d', self.name, self.vis_gain_day, self.ir_gain_day)
            self.si1145.vis_gain = self.vis_gain_day
            self.si1145.ir_gain = self.ir_gain_day

        time.sleep(1.0)


class LightSensorSi1145_I2C(LightSensorSi1145):

    METADATA = {
        'name' : 'SI1145 (i2c)',
        'description' : 'SI1145 i2c UV Light Sensor',
        'count' : 3,
        'labels' : (
            'Visible',
            'IR',
            'UV Index',
        ),
        'types' : (
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
            constants.SENSOR_LIGHT_MISC,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(LightSensorSi1145_I2C, self).__init__(*args, **kwargs)

        i2c_address_str = kwargs['i2c_address']

        import board
        import adafruit_si1145

        i2c_address = int(i2c_address_str, 16)  # string in config

        logger.warning('Initializing [%s] SI1145 I2C light sensor device @ %s', self.name, hex(i2c_address))
        i2c = board.I2C()
        self.si1145 = adafruit_si1145.SI1145(i2c, address=i2c_address)

        # enable UV index
        self.si1145.uv_index_enabled = True


        self.vis_gain_night = getattr(adafruit_si1145, self.config.get('TEMP_SENSOR', {}).get('SI1145_VIS_GAIN_NIGHT', 'GAIN_ADC_CLOCK_DIV_32'))
        self.vis_gain_day = getattr(adafruit_si1145, self.config.get('TEMP_SENSOR', {}).get('SI1145_VIS_GAIN_DAY', 'GAIN_ADC_CLOCK_DIV_1'))
        self.ir_gain_night = getattr(adafruit_si1145, self.config.get('TEMP_SENSOR', {}).get('SI1145_IR_GAIN_NIGHT', 'GAIN_ADC_CLOCK_DIV_32'))
        self.ir_gain_day = getattr(adafruit_si1145, self.config.get('TEMP_SENSOR', {}).get('SI1145_IR_GAIN_DAY', 'GAIN_ADC_CLOCK_DIV_1'))

        time.sleep(1.0)

