from multiprocessing import Array
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from indi_allsky.devices.sensors.tempSensorBme280 import TempSensorBme280
from indi_allsky.devices.sensors.tempSensorBme680 import TempSensorBme680
from indi_allsky.devices.sensors.tempSensorBmp280 import TempSensorBmp280
from indi_allsky.devices.sensors.tempSensorBmp3xx import TempSensorBmp3xx
from indi_allsky.devices.sensors.tempSensorSht3x import TempSensorSht3x
from indi_allsky.devices.sensors.tempSensorSht4x import TempSensorSht4x
from indi_allsky.devices.sensors.tempSensorSi7021 import TempSensorSi7021
from indi_allsky.devices.sensors.tempSensorHtu21d import TempSensorHtu21d
from indi_allsky.devices.sensors.tempSensorHtu31d import TempSensorHtu31d
from indi_allsky.devices.sensors.lightSensorTsl2561 import LightSensorTsl2561
from indi_allsky.devices.sensors.tempSensorDht import TempSensorDht2x
from indi_allsky.devices.sensors.currentSensorIna219 import CurrentSensorIna219
from indi_allsky.devices.sensors.currentSensorIna3221 import CurrentSensorIna3221
from indi_allsky.devices.sensors.lightSensorSi1145 import LightSensorSi1145, LightSensorSi1145_I2C
from indi_allsky.devices.sensors.lightSensorTsl2591 import LightSensorTsl2591, LightSensorTsl2591_I2C
from indi_allsky.devices.sensors.mqttBrokerSensor import MqttBrokerSensor
from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky import constants


def test_bme280_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBme280(config, "TestBme280", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bme280 = MagicMock(
        temperature=22.5,
        humidity=45.0,
        pressure=1013.25,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 4
    assert data['data'][0] == 22.5
    assert data['data'][1] == 45.0
    assert data['data'][2] == 1013.25
    assert data['data'][3] == pytest.approx(10.0, abs=0.5)
    assert 'dew_point' in data
    assert 'heat_index' in data


def test_bme680_update():
    config = {
        'TEMP_DISPLAY': 'f',
        'PRESSURE_DISPLAY': 'inHg',
    }
    sensor = TempSensorBme680(config, "TestBme680", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bme680 = MagicMock(
        temperature=20.0,
        humidity=50.0,
        pressure=1000.0,
        gas=15000,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 5
    # Fahrenheit check (20C = 68F)
    assert data['data'][0] == 68.0
    assert data['data'][1] == 50.0
    assert data['data'][2] == pytest.approx(29.53, abs=0.01)
    assert data['data'][3] == 15000
    assert data['data'][4] == pytest.approx(48.7, abs=0.5)


def test_bmp280_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBmp280(config, "TestBmp280", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bmp280 = MagicMock(
        temperature=24.0,
        pressure=1010.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 2
    assert data['data'][0] == 24.0
    assert data['data'][1] == 1010.0


def test_bmp3xx_update():
    config = {
        'TEMP_DISPLAY': 'c',
        'PRESSURE_DISPLAY': 'hPa',
    }
    sensor = TempSensorBmp3xx(config, "TestBmp3xx", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.bmp3xx = MagicMock(
        temperature=21.0,
        pressure=1012.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 2
    assert data['data'][0] == 21.0
    assert data['data'][1] == 1012.0


def test_sht3x_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSht3x(config, "TestSht3x", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_night = False
    sensor.heater_day = False
    sensor.heater_available = False
    sensor.sht3x = MagicMock(
        temperature=23.0,
        relative_humidity=55.0,
        heater=False,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 23.0
    assert data['data'][1] == 55.0


def test_sht4x_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSht4x(config, "TestSht4x", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.mode_night = 0
    sensor.mode_day = 0
    sensor.heater_available = False
    sensor.sht4x = MagicMock(
        measurements=(25.0, 50.0),
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 25.0
    assert data['data'][1] == 50.0


def test_si7021_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorSi7021(config, "TestSi7021", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_level_night = -1
    sensor.heater_level_day = -1
    sensor.heater_available = False
    sensor.si7021 = MagicMock(
        temperature=22.0,
        relative_humidity=60.0,
        heater_enable=False,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 22.0
    assert data['data'][1] == 60.0


def test_htu21d_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    sensor = TempSensorHtu21d(config, "TestHtu21d", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.htu21d = MagicMock(
        temperature=19.5,
        relative_humidity=52.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 19.5
    assert data['data'][1] == 52.0


def test_htu31d_update():
    config = {
        'TEMP_DISPLAY': 'c',
    }
    night_av = Array('i', [0]*10)
    sensor = TempSensorHtu31d(config, "TestHtu31d", night_av, Array('f', [0.0]*10))
    sensor.night = False
    sensor.heater_night = False
    sensor.heater_day = False
    sensor.heater_available = False
    sensor.htu31d = MagicMock(
        temperature=20.5,
        relative_humidity=48.0,
        heater=False,
    )


    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 20.5
    assert data['data'][1] == 48.0


def test_ina219_update():
    config = {}
    sensor = CurrentSensorIna219(config, "TestIna219", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.ina219 = MagicMock(
        bus_voltage=12.0,
        shunt_voltage=0.05,
        current=500.0,  # 500 mA
        power=6.0,      # 6 Watts
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 12.05
    assert data['data'][1] == 0.5
    assert data['data'][2] == 6.0


def test_ina3221_get_channel():
    config = {}
    sensor = CurrentSensorIna3221(config, "TestIna3221", Array('i', [0]*10), Array('f', [0.0]*10))
    mock_ch0 = MagicMock(bus_voltage=12.0, shunt_voltage=0.01, current=1.0)
    sensor.ina3221 = (mock_ch0,)

    v, a, w = sensor.getChannel(0)
    assert v == 12.0
    assert a == 1000.0
    assert w == 12000.0


def test_tsl2561_update():
    config = {}
    sensor = LightSensorTsl2561(config, "TestTsl2561", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.tsl2561 = MagicMock(
        lux=250.0,
        broadband=3000,
        infrared=1200,
    )
    sensor.gain_night = 1
    sensor.gain_day = 0
    sensor.integration_night = 1
    sensor.integration_day = 1
    sensor.disable_day = False

    with patch('time.sleep', return_value=None):
        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 5
        assert data['data'][0] == 250.0
        assert data['data'][1] == 3000
        assert data['data'][2] == 1200


def test_dht_update():
    config = {'TEMP_DISPLAY': 'c'}
    sensor = TempSensorDht2x(config, "TestDht", Array('i', [0]*10), Array('f', [0.0]*10))
    sensor.dht = MagicMock(
        temperature=18.0,
        humidity=60.0,
    )

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 3
    assert data['data'][0] == 18.0
    assert data['data'][1] == 60.0
    assert data['data'][2] == pytest.approx(10.1, abs=0.5)


import sys
from indi_allsky.devices.sensors.lightningSensorAs3935 import (
    LightningSensorAs3935_SparkFun,
    LightningSensorAs3935_SparkFun_I2C,
    LightningSensorAs3935_SparkFun_SPI,
)
from indi_allsky.devices.exceptions import SensorException, DeviceControlException


def test_as3935_sparkfun_update_and_callback():
    config = {
        'TEMP_DISPLAY': 'c',
        'TEMP_SENSOR': {
            'AS3935_OUTDOOR_MODE': True,
            'AS3935_MASK_DISTURBER': True,
            'AS3935_NOISE_LEVEL': 3,
            'AS3935_SPIKE_REJECTION': 4,
        },
    }
    sensor = LightningSensorAs3935_SparkFun(config, "TestAS3935", Array('i', [0]*10), Array('f', [0.0]*10))
    mock_as3935 = MagicMock()
    mock_as3935.NOISE = 1
    mock_as3935.DISTURBER = 2
    mock_as3935.LIGHTNING = 3
    sensor.as3935 = mock_as3935

    # 1. Update with empty data
    empty_data = sensor.update()
    assert empty_data['data'] == (0, 0, 0, 0.0, 0, 0)

    # 2. Callback for NOISE
    mock_as3935.read_interrupt_register.return_value = mock_as3935.NOISE
    sensor.detection_callback(1)
    assert sensor.full_noise_count == 1
    assert sensor.current_data_dict['noise_count'] == 1

    # 3. Callback for DISTURBER
    mock_as3935.read_interrupt_register.return_value = mock_as3935.DISTURBER
    sensor.detection_callback(1)
    assert sensor.full_disturber_count == 1
    assert sensor.current_data_dict['disturber_count'] == 1

    # 4. Callback for LIGHTNING
    mock_as3935.read_interrupt_register.return_value = mock_as3935.LIGHTNING
    mock_as3935.distance_to_storm = 15
    mock_as3935.lightning_energy = 500
    sensor.detection_callback(1)
    assert sensor.current_data_dict['distance_list'] == [15]
    assert sensor.current_data_dict['energy_list'] == [500]

    # 5. Update with data (Celsius mode)
    # sensor.update appends current_data_dict to full_data_list
    data_c = sensor.update()
    # Now distance_list is empty because update resets it for the NEXT cycle, but full_data_list has 1 entry
    data_c2 = sensor.update()
    assert data_c2['data'][0] == 1  # 1 strike total
    assert data_c2['data'][1] == 15  # min
    assert data_c2['data'][2] == 15  # max
    assert data_c2['data'][3] == 15.0  # avg

    # 6. Update with Fahrenheit mode
    sensor.config['TEMP_DISPLAY'] = 'f'
    data_f = sensor.update()
    expected_miles = sensor.km2mi(15)
    assert data_f['data'][1] == expected_miles

    # 7. deinit
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    with patch.dict(sys.modules, {'RPi': mock_rpi, 'RPi.GPIO': mock_gpio}):
        sensor.deinit()
        mock_gpio.cleanup.assert_called_once()


def test_as3935_sparkfun_i2c_init():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_board = MagicMock()
    mock_board.D4 = MagicMock(id=4)
    mock_sparkfun = MagicMock()
    mock_chip = MagicMock()
    mock_chip.connected = True
    mock_chip.calibrate.side_effect = [False, True]
    mock_sparkfun.Sparkfun_QwiicAS3935_I2C.return_value = mock_chip

    config = {
        'TEMP_SENSOR': {
            'AS3935_OUTDOOR_MODE': False,
        }
    }

    # Missing pin_2_name
    with pytest.raises(SensorException):
        LightningSensorAs3935_SparkFun_I2C(
            config, "AS3935_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x03', pin_2_name='',
        )

    with patch.dict(sys.modules, {
        'RPi': mock_rpi,
        'RPi.GPIO': mock_gpio,
        'board': mock_board,
        'sparkfun_qwiicas3935': mock_sparkfun,
    }), patch('time.sleep', return_value=None):
        # Successful init
        sensor = LightningSensorAs3935_SparkFun_I2C(
            config, "AS3935_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x03', pin_2_name='D4',
        )
        assert sensor.as3935 == mock_chip
        mock_chip.reset.assert_called_once()
        assert mock_chip.calibrate.call_count == 2
        mock_gpio.setup.assert_called_with(4, mock_gpio.IN, pull_up_down=mock_gpio.PUD_UP)
        mock_gpio.add_event_detect.assert_called_once()

        # Outdoor mode
        config_outdoor = {'TEMP_SENSOR': {'AS3935_OUTDOOR_MODE': True}}
        mock_chip.calibrate.side_effect = [True]
        LightningSensorAs3935_SparkFun_I2C(
            config_outdoor, "AS3935_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x03', pin_2_name='D4',
        )

        # Not connected failure
        mock_chip.connected = False
        with pytest.raises(SensorException):
            LightningSensorAs3935_SparkFun_I2C(
                config, "AS3935_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x03', pin_2_name='D4',
            )

        # Device init exception
        mock_sparkfun.Sparkfun_QwiicAS3935_I2C.side_effect = RuntimeError("I2C error")
        with pytest.raises(DeviceControlException):
            LightningSensorAs3935_SparkFun_I2C(
                config, "AS3935_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x03', pin_2_name='D4',
            )


def test_as3935_sparkfun_spi_init():
    mock_rpi = MagicMock()
    mock_gpio = MagicMock()
    mock_rpi.GPIO = mock_gpio
    mock_board = MagicMock()
    mock_board.D4 = MagicMock(id=4)
    mock_board.D5 = MagicMock(id=5)
    mock_digitalio = MagicMock()
    mock_sparkfun = MagicMock()
    mock_chip = MagicMock()
    mock_chip.connected = True
    mock_chip.calibrate.side_effect = [False, True]
    mock_sparkfun.Sparkfun_QwiicAS3935_SPI.return_value = mock_chip

    config = {
        'TEMP_SENSOR': {
            'AS3935_OUTDOOR_MODE': True,
        }
    }

    # Missing pin_2_name
    with pytest.raises(SensorException):
        LightningSensorAs3935_SparkFun_SPI(
            config, "AS3935_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D5', pin_2_name='',
        )

    with patch.dict(sys.modules, {
        'RPi': mock_rpi,
        'RPi.GPIO': mock_gpio,
        'board': mock_board,
        'digitalio': mock_digitalio,
        'sparkfun_qwiicas3935': mock_sparkfun,
    }), patch('time.sleep', return_value=None):
        # Successful init
        sensor = LightningSensorAs3935_SparkFun_SPI(
            config, "AS3935_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D5', pin_2_name='D4',
        )
        assert sensor.as3935 == mock_chip
        mock_chip.reset.assert_called_once()
        mock_gpio.setup.assert_called_with(4, mock_gpio.IN, pull_up_down=mock_gpio.PUD_UP)
        mock_gpio.add_event_detect.assert_called_once()

        # Indoor mode
        config_indoor = {'TEMP_SENSOR': {'AS3935_OUTDOOR_MODE': False}}
        mock_chip.calibrate.side_effect = [True]
        LightningSensorAs3935_SparkFun_SPI(
            config_indoor, "AS3935_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D5', pin_2_name='D4',
        )

        # Not connected failure
        mock_chip.connected = False
        with pytest.raises(SensorException):
            LightningSensorAs3935_SparkFun_SPI(
                config, "AS3935_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D5', pin_2_name='D4',
            )

        # Device init exception
        mock_sparkfun.Sparkfun_QwiicAS3935_SPI.side_effect = RuntimeError("SPI error")
        with pytest.raises(DeviceControlException):
            LightningSensorAs3935_SparkFun_SPI(
                config, "AS3935_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D5', pin_2_name='D4',
            )


def test_si1145_update_and_modes():
    config = {
        'TEMP_SENSOR': {
            'SI1145_VIS_GAIN_NIGHT': 'GAIN_ADC_CLOCK_DIV_32',
            'SI1145_VIS_GAIN_DAY': 'GAIN_ADC_CLOCK_DIV_1',
            'SI1145_IR_GAIN_NIGHT': 'GAIN_ADC_CLOCK_DIV_32',
            'SI1145_IR_GAIN_DAY': 'GAIN_ADC_CLOCK_DIV_1',
            'SI1145_VIS_RANGE_HIGH_NIGHT': False,
            'SI1145_VIS_RANGE_HIGH_DAY': True,
            'SI1145_IR_RANGE_HIGH_NIGHT': False,
            'SI1145_IR_RANGE_HIGH_DAY': True,
        }
    }
    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = -20.0  # night mode

    sensor = LightSensorSi1145(config, "SI1145", Array('i', [0]*10), astro_av)
    sensor.si1145 = MagicMock()
    sensor.vis_gain_night = 32
    sensor.vis_gain_day = 1
    sensor.ir_gain_night = 32
    sensor.ir_gain_day = 1
    sensor.vis_range_high_night = False
    sensor.vis_range_high_day = True
    sensor.ir_range_high_night = False
    sensor.ir_range_high_day = True

    sensor.si1145.als = (150, 80)
    sensor.si1145.uv_index = 0.5

    with patch('time.sleep', return_value=None):
        # 1. Night update
        data = sensor.update()
        assert data['data'][0] == 150
        assert data['data'][1] == 80
        assert data['data'][2] == 0.5
        assert sensor.astro_darkness is True
        assert sensor.si1145.vis_gain == 32

        # 2. Day update
        astro_av[constants.ASTRO_SUN_ALT] = 5.0
        data_day = sensor.update()
        assert sensor.astro_darkness is False
        assert sensor.si1145.vis_gain == 1
        assert data_day['data'][3] == 0.0  # SQM 0 outside darkness

        # 3. SQM calculation ValueError
        astro_av[constants.ASTRO_SUN_ALT] = -25.0
        sensor._astro_darkness = None
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("math error")):
            data_err = sensor.update()
            assert data_err['data'][3] == 0.0

        # 4. RuntimeError handling
        type(sensor.si1145).als = PropertyMock(side_effect=RuntimeError("bus read failed"))
        with pytest.raises(SensorReadException):
            sensor.update()

        # 5. TypeError handling
        type(sensor.si1145).als = PropertyMock(return_value=(None, None))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_si1145_i2c_init():
    mock_board = MagicMock()
    mock_adafruit_si1145 = MagicMock()
    mock_chip = MagicMock()
    mock_adafruit_si1145.SI1145.return_value = mock_chip
    mock_adafruit_si1145.GAIN_ADC_CLOCK_DIV_32 = 32
    mock_adafruit_si1145.GAIN_ADC_CLOCK_DIV_1 = 1

    config = {'TEMP_SENSOR': {}}

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_si1145': mock_adafruit_si1145,
    }), patch('time.sleep', return_value=None):
        sensor = LightSensorSi1145_I2C(
            config, "SI1145_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x60',
        )
        assert sensor.si1145 is mock_chip
        assert mock_chip.uv_index_enabled is True

        # Init error raises DeviceControlException
        mock_adafruit_si1145.SI1145.side_effect = RuntimeError("I2C failure")
        with pytest.raises(DeviceControlException):
            LightSensorSi1145_I2C(
                config, "SI1145_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x60',
            )


def test_tsl2591_update_and_modes():
    config = {
        'TEMP_SENSOR': {
            'TSL2591_DISABLE_DAY': False,
        }
    }
    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = -20.0  # night

    sensor = LightSensorTsl2591(config, "TSL2591", Array('i', [0]*10), astro_av)
    sensor.tsl2591 = MagicMock(
        lux=0.0123,
        infrared=50,
        visible=120,
        full_spectrum=170,
    )
    sensor.gain_night = 25
    sensor.gain_day = 1
    sensor.integration_night = 100
    sensor.integration_day = 100
    sensor.disable_day = False

    with patch('time.sleep', return_value=None):
        # 1. Night update
        data = sensor.update()
        assert data['sqm_mag'] > 0
        assert data['data'][0] == pytest.approx(0.0123)
        assert data['data'][1] == 120
        assert data['data'][2] == 50
        assert data['data'][3] == 170
        assert sensor.tsl2591.gain == 25

        # 2. Day update with disable_day=True
        sensor.disable_day = True
        data_disabled = sensor.update()
        assert data_disabled['data'] == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # 3. Day update with disable_day=False
        sensor.disable_day = False
        astro_av[constants.ASTRO_SUN_ALT] = 10.0
        data_day = sensor.update()
        assert sensor.tsl2591.gain == 1
        assert data_day['sqm_mag'] == 0.0

        # 4. SQM calculation ValueError
        astro_av[constants.ASTRO_SUN_ALT] = -25.0
        sensor._astro_darkness = None
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("math error")):
            data_err = sensor.update()
            assert data_err['sqm_mag'] == 0.0

        # 5. RuntimeError handling
        type(sensor.tsl2591).lux = PropertyMock(side_effect=RuntimeError("I2C read fail"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_tsl2591_i2c_init():
    mock_board = MagicMock()
    mock_adafruit_tsl2591 = MagicMock()
    mock_chip = MagicMock()
    mock_adafruit_tsl2591.TSL2591.return_value = mock_chip
    mock_adafruit_tsl2591.GAIN_MED = 25
    mock_adafruit_tsl2591.GAIN_LOW = 1
    mock_adafruit_tsl2591.INTEGRATIONTIME_100MS = 100

    config = {'TEMP_SENSOR': {'TSL2591_DISABLE_DAY': True}}

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_tsl2591': mock_adafruit_tsl2591,
    }), patch('time.sleep', return_value=None):
        sensor = LightSensorTsl2591_I2C(
            config, "TSL2591_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x29',
        )
        assert sensor.tsl2591 is mock_chip
        assert sensor.disable_day is True

        # Error during init
        mock_adafruit_tsl2591.TSL2591.side_effect = RuntimeError("I2C fail")
        with pytest.raises(DeviceControlException):
            LightSensorTsl2591_I2C(
                config, "TSL2591_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x29',
            )


def test_mqtt_broker_sensor_get_labels():
    # Home Assistant state convention
    pin_1 = 'home/sensor/temp_outdoor/state,home/sensor/humidity-outdoor/state,standalone_sensor'
    labels = MqttBrokerSensor.get_labels(pin_1)
    assert len(labels) == 10
    assert labels[0] == 'temp outdoor'
    assert labels[1] == 'humidity outdoor'
    assert labels[2] == 'standalone sensor'
    assert labels[3] == 'Topic 4'
    assert labels[9] == 'Topic 10'

    # Empty pin_1_name
    empty_labels = MqttBrokerSensor.get_labels('')
    assert len(empty_labels) == 10
    assert empty_labels[0] == 'Topic 1'


def test_mqtt_broker_sensor_lifecycle():
    import ssl
    import paho.mqtt.client as mqtt

    mock_client = MagicMock()
    config = {
        'TEMP_SENSOR': {
            'MQTT_TRANSPORT': 'tcp',
            'MQTT_PROTOCOL': 'MQTTv5',
            'MQTT_HOST': 'broker.local',
            'MQTT_PORT': 1883,
            'MQTT_USERNAME': 'user',
            'MQTT_PASSWORD': 'pass',
            'MQTT_TLS': True,
            'MQTT_CERT_BYPASS': True,
        }
    }

    with patch('paho.mqtt.client.Client', return_value=mock_client):
        sensor = MqttBrokerSensor(
            config, "MQTT_Sensor", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='topic1,topic2',
        )
        assert sensor.topic_list == ['topic1', 'topic2']
        mock_client.username_pw_set.assert_called_with(username='user', password='pass')
        mock_client.tls_set.assert_called()
        mock_client.loop_start.assert_called_once()

        # Test update
        data = sensor.update()
        assert len(data['data']) == 10

        # Test on_connect
        mock_reason_ok = MagicMock(is_failure=False)
        sensor.on_connect(mock_client, sensor.data, None, mock_reason_ok, None)
        assert mock_client.subscribe.call_count == 2

        mock_reason_fail = MagicMock(is_failure=True)
        sensor.on_connect(mock_client, sensor.data, None, mock_reason_fail, None)

        # Test on_disconnect
        sensor.on_disconnect(mock_client, sensor.data, None, mock_reason_fail, None)

        # Test on_subscribe
        mock_sub_reason_ok = [MagicMock(is_failure=False, value=1)]
        sensor.on_subscribe(mock_client, sensor.data, 1, mock_sub_reason_ok, None)
        mock_sub_reason_fail = [MagicMock(is_failure=True)]
        sensor.on_subscribe(mock_client, sensor.data, 1, mock_sub_reason_fail, None)

        # Test on_unsubscribe
        sensor.on_unsubscribe(mock_client, sensor.data, 1, mock_sub_reason_ok, None)
        sensor.on_unsubscribe(mock_client, sensor.data, 1, mock_sub_reason_fail, None)
        sensor.on_unsubscribe(mock_client, sensor.data, 1, [], None)

        # Test on_message
        msg_ok = MagicMock(payload=b'23.5', topic='topic1')
        sensor.on_message(mock_client, sensor.data, msg_ok)
        assert sensor.data['data'][0] == 23.5

        # Invalid float value
        msg_bad_val = MagicMock(payload=b'not-a-number', topic='topic1')
        sensor.on_message(mock_client, sensor.data, msg_bad_val)

        # Unknown topic
        msg_unknown_topic = MagicMock(payload=b'10.0', topic='unknown_topic')
        sensor.on_message(mock_client, sensor.data, msg_unknown_topic)

        # Test ConnectionRefusedError during connect
        mock_client.connect.side_effect = ConnectionRefusedError("Broker offline")
        MqttBrokerSensor(
            config, "MQTT_Sensor_Offline", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='topic1',
        )

        # Unknown protocol raises AttributeError
        bad_config = {'TEMP_SENSOR': {'MQTT_PROTOCOL': 'UNKNOWN_PROTO'}}
        with pytest.raises(AttributeError):
            MqttBrokerSensor(
                bad_config, "MQTT_Sensor_Bad", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='topic1',
            )

