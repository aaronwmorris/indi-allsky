import sys
from multiprocessing import Array
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from indi_allsky import constants
from indi_allsky.devices.exceptions import SensorReadException, DeviceControlException, SensorException
from indi_allsky.devices.sensors.lightSensorBh1750 import LightSensorBh1750, LightSensorBh1750_I2C
from indi_allsky.devices.sensors.lightSensorLtr390 import LightSensorLtr390, LightSensorLtr390_I2C
from indi_allsky.devices.sensors.lightSensorTsl2561 import LightSensorTsl2561, LightSensorTsl2561_I2C
from indi_allsky.devices.sensors.lightSensorVeml7700 import LightSensorVeml7700, LightSensorVeml7700_I2C
from indi_allsky.devices.sensors.rainSensorFc37 import RainSensorFc37
from indi_allsky.devices.sensors.imuSensorIcm20x import ImuSensorIcm20x, ImuSensorIcm20x_I2C
from indi_allsky.devices.sensors.imuSensorMpu6050 import ImuSensorMpu6050, ImuSensorMpu6050_I2C
from indi_allsky.devices.sensors.magSensorMmc5983ma import MagSensorMmc5983maSF, MagSensorMmc5983maSF_I2C
from indi_allsky.devices.sensors.vocSensorSgp40 import VocSensorSgp40, VocSensorSgp40_I2C


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- BH1750 ---

def test_bh1750_i2c():
    mock_board = MagicMock()
    mock_bh1750_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bh1750_mod.BH1750.return_value = mock_dev

    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = -20.0  # Astro darkness

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_bh1750': mock_bh1750_mod}):
        sensor = LightSensorBh1750_I2C(
            {}, "BH1750_Test", Array('i', [0]*10), astro_av,
            i2c_address='0x23',
        )
        mock_dev.lux = 10.0

        # Astro darkness: calculates SQM
        data = sensor.update()
        assert data['sqm_mag'] > 0
        assert data['data'][0] == 10.0

        # Daytime: SQM = 0
        astro_av[constants.ASTRO_SUN_ALT] = 0.0
        data_day = sensor.update()
        assert data_day['sqm_mag'] == 0.0

        # ValueError during lux2mag
        astro_av[constants.ASTRO_SUN_ALT] = -20.0
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("bad lux")):
            data_err = sensor.update()
            assert data_err['sqm_mag'] == 0.0

        # Exceptions
        type(mock_dev).lux = PropertyMock(side_effect=RuntimeError("Bus error"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(mock_dev).lux = PropertyMock(side_effect=TypeError("Type error"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_bh1750_init_exception():
    mock_board = MagicMock()
    mock_bh1750_mod = MagicMock()
    mock_bh1750_mod.BH1750.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_bh1750': mock_bh1750_mod}):
        with pytest.raises(DeviceControlException):
            LightSensorBh1750_I2C(
                {}, "BH1750_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x23',
            )


# --- LTR390 ---

def test_ltr390_i2c():
    mock_board = MagicMock()
    mock_ltr390_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ltr390_mod.LTR390.return_value = mock_dev
    mock_ltr390_mod.Gain.GAIN_9X = 9
    mock_ltr390_mod.Gain.GAIN_1X = 1

    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = 5.0  # Daytime

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ltr390': mock_ltr390_mod}):
        sensor = LightSensorLtr390_I2C(
            {}, "LTR390_Test", Array('i', [0]*10), astro_av,
            i2c_address='0x53',
        )
        mock_dev.uvs = 100
        mock_dev.light = 500
        mock_dev.uvi = 1.2
        mock_dev.lux = 50.0

        # Daytime update
        data_day = sensor.update()
        assert data_day['sqm_mag'] == 0.0
        assert mock_dev.gain == 1

        # Transition to night mode
        astro_av[constants.ASTRO_SUN_ALT] = -25.0
        data_night = sensor.update()
        assert data_night['sqm_mag'] > 0.0
        assert mock_dev.gain == 9

        # ValueError during lux2mag
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("bad lux")):
            data_val_err = sensor.update()
            assert data_val_err['sqm_mag'] == 0.0

        # Read error
        type(mock_dev).uvs = PropertyMock(side_effect=RuntimeError("Read fail"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_ltr390_init_exception():
    mock_board = MagicMock()
    mock_ltr390_mod = MagicMock()
    mock_ltr390_mod.LTR390.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ltr390': mock_ltr390_mod}):
        with pytest.raises(DeviceControlException):
            LightSensorLtr390_I2C(
                {}, "LTR390_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x53',
            )


# --- TSL2561 ---

def test_tsl2561_i2c():
    mock_board = MagicMock()
    mock_tsl2561_mod = MagicMock()
    mock_dev = MagicMock()
    mock_tsl2561_mod.TSL2561.return_value = mock_dev

    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = 10.0  # Daytime

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_tsl2561': mock_tsl2561_mod}):
        # Daytime disabled
        sensor_disabled = LightSensorTsl2561_I2C(
            {'TEMP_SENSOR': {'TSL2561_DISABLE_DAY': True}},
            "TSL_Dis", Array('i', [0]*10), astro_av,
            i2c_address='0x39',
        )
        assert sensor_disabled.update() == {'data': (0.0, 0.0, 0.0, 0.0, 0.0)}

        # Normal sensor
        sensor = LightSensorTsl2561_I2C(
            {}, "TSL_Normal", Array('i', [0]*10), astro_av,
            i2c_address='0x39',
        )
        mock_dev.lux = 25.0
        mock_dev.broadband = 300
        mock_dev.infrared = 100

        data_day = sensor.update()
        assert data_day['sqm_mag'] == 0.0

        # Switch to night
        astro_av[constants.ASTRO_SUN_ALT] = -20.0
        data_night = sensor.update()
        assert data_night['sqm_mag'] > 0.0

        # ValueError during lux2mag
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("calc error")):
            assert sensor.update()['sqm_mag'] == 0.0

        # Read error
        type(mock_dev).lux = PropertyMock(side_effect=RuntimeError("Bus err"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(mock_dev).lux = PropertyMock(side_effect=TypeError("Type err"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_tsl2561_init_exception():
    mock_board = MagicMock()
    mock_tsl2561_mod = MagicMock()
    mock_tsl2561_mod.TSL2561.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_tsl2561': mock_tsl2561_mod}):
        with pytest.raises(DeviceControlException):
            LightSensorTsl2561_I2C(
                {}, "TSL_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x39',
            )


# --- VEML7700 ---

def test_veml7700_i2c():
    mock_board = MagicMock()
    mock_veml7700_mod = MagicMock()
    mock_dev = MagicMock()
    mock_veml7700_mod.VEML7700.return_value = mock_dev
    mock_veml7700_mod.VEML7700.ALS_GAIN_2 = 2
    mock_veml7700_mod.VEML7700.ALS_GAIN_1_8 = 0.125
    mock_veml7700_mod.VEML7700.ALS_100MS = 100

    astro_av = Array('f', [0.0] * 10)
    astro_av[constants.ASTRO_SUN_ALT] = 5.0

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_veml7700': mock_veml7700_mod}):
        sensor = LightSensorVeml7700_I2C(
            {}, "VEML_Test", Array('i', [0]*10), astro_av,
            i2c_address='0x10',
        )
        mock_dev.lux = 12.5
        mock_dev.light = 400
        mock_dev.white = 600

        data_day = sensor.update()
        assert data_day['sqm_mag'] == 0.0

        # Switch to night
        astro_av[constants.ASTRO_SUN_ALT] = -22.0
        data_night = sensor.update()
        assert data_night['sqm_mag'] > 0.0

        # ValueError during lux2mag
        with patch.object(sensor, 'lux2mag', side_effect=ValueError("bad")):
            assert sensor.update()['sqm_mag'] == 0.0

        # Exceptions
        type(mock_dev).lux = PropertyMock(side_effect=RuntimeError("Bus err"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(mock_dev).lux = PropertyMock(side_effect=TypeError("Type err"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_veml7700_init_exception():
    mock_board = MagicMock()
    mock_veml7700_mod = MagicMock()
    mock_veml7700_mod.VEML7700.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_veml7700': mock_veml7700_mod}):
        with pytest.raises(DeviceControlException):
            LightSensorVeml7700_I2C(
                {}, "VEML_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x10',
            )


# --- RainSensorFc37 ---

def test_fc37_rain_sensor():
    mock_board = MagicMock(spec=['D4'])
    mock_board.D4 = 'D4'
    mock_digitalio = MagicMock()
    mock_pin = MagicMock()
    mock_digitalio.DigitalInOut.return_value = mock_pin

    # Missing pin
    with pytest.raises(SensorException, match='pin not configured'):
        RainSensorFc37({}, "FC37", Array('i', [0]*10), Array('f', [0.0]*10))

    # Missing digitalio
    with patch.dict(sys.modules, {'board': None, 'digitalio': None}):
        with pytest.raises(SensorException, match='requires board/digitalio'):
            RainSensorFc37({}, "FC37", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='D4')

    with patch.dict(sys.modules, {'board': mock_board, 'digitalio': mock_digitalio}):
        # Invalid pin name
        with pytest.raises(SensorException, match='is not valid'):
            RainSensorFc37({}, "FC37", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='D99')

        # Normal active-low: low = rain, high = dry
        sensor = RainSensorFc37(
            {'TEMP_SENSOR': {'FC37_ACTIVE_LOW': True}},
            "FC37_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D4',
        )
        mock_pin.value = False  # Raining (active low)
        data = sensor.update()
        assert data['rain'] == 1
        assert data['data'] == (1,)

        mock_pin.value = True   # No rain
        data_dry = sensor.update()
        assert data_dry['rain'] == 0

        # active-high
        sensor_ah = RainSensorFc37(
            {'TEMP_SENSOR': {'FC37_ACTIVE_LOW': False}},
            "FC37_AH", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D4',
        )
        mock_pin.value = True
        assert sensor_ah.update()['rain'] == 1

        # Read failure
        type(mock_pin).value = PropertyMock(side_effect=RuntimeError("Read fail"))
        with pytest.raises(SensorException, match='read failure'):
            sensor.update()

        # Deinit
        sensor.deinit()
        mock_pin.deinit.assert_called()

        # Deinit exception handled gracefully
        mock_pin.deinit.side_effect = Exception("deinit error")
        sensor.deinit()


# --- ICM20X ---

def test_icm20x_i2c():
    mock_board = MagicMock()
    mock_icm_mod = MagicMock()
    mock_dev = MagicMock()
    mock_icm_mod.ICM20948.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_icm20x': mock_icm_mod}):
        sensor = ImuSensorIcm20x_I2C(
            {}, "ICM_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x69',
        )
        mock_dev.magnetic = (1.5, -2.0, 3.25)
        data = sensor.update()
        assert data['data'] == (1.5, -2.0, 3.25)

        type(mock_dev).magnetic = PropertyMock(side_effect=RuntimeError("Mag error"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(mock_dev).magnetic = PropertyMock(side_effect=TypeError("Type error"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_icm20x_init_exception():
    mock_board = MagicMock()
    mock_icm_mod = MagicMock()
    mock_icm_mod.ICM20948.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_icm20x': mock_icm_mod}):
        with pytest.raises(DeviceControlException):
            ImuSensorIcm20x_I2C(
                {}, "ICM_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x69',
            )


# --- MPU6050 ---

def test_mpu6050_i2c():
    mock_board = MagicMock()
    mock_mpu_mod = MagicMock()
    mock_dev = MagicMock()
    mock_mpu_mod.MPU6050.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_mpu6050': mock_mpu_mod}):
        sensor = ImuSensorMpu6050_I2C(
            {'TEMP_DISPLAY': 'c'}, "MPU_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x68',
        )
        mock_dev.temperature = 24.5
        assert sensor.update()['data'] == (24.5,)

        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'] == (pytest.approx(76.1),)

        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'] == (pytest.approx(297.65),)

        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Bus err"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_mpu6050_init_exception():
    mock_board = MagicMock()
    mock_mpu_mod = MagicMock()
    mock_mpu_mod.MPU6050.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_mpu6050': mock_mpu_mod}):
        with pytest.raises(DeviceControlException):
            ImuSensorMpu6050_I2C(
                {}, "MPU_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x68',
            )


# --- MMC5983MA ---

def test_mmc5983ma_i2c():
    mock_qwiic_mod = MagicMock()
    mock_dev = MagicMock()
    mock_qwiic_mod.QwiicMMC5983MA.return_value = mock_dev

    with patch.dict(sys.modules, {'qwiic_mmc5983ma': mock_qwiic_mod}):
        mock_dev.is_connected.return_value = True
        mock_dev.get_measurement_xyz_gauss.return_value = (0.1, -0.2, 0.5)
        mock_dev.get_temperature.return_value = 26.0

        sensor = MagSensorMmc5983maSF_I2C(
            {'TEMP_DISPLAY': 'c'}, "MMC_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x30',
        )
        mock_dev.begin.assert_called_once()

        data = sensor.update()
        assert data['data'] == (0.1, -0.2, 0.5, 26.0)

        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][3] == pytest.approx(78.8)

        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][3] == pytest.approx(299.15)

        # TypeError during update
        mock_dev.get_measurement_xyz_gauss.side_effect = TypeError("Read fail")
        with pytest.raises(SensorReadException):
            sensor.update()

        # is_connected False
        mock_dev.is_connected.return_value = False
        with pytest.raises(Exception, match='not connected'):
            MagSensorMmc5983maSF_I2C(
                {}, "MMC_NotConn", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x30',
            )


def test_mmc5983ma_init_exception():
    mock_qwiic_mod = MagicMock()
    mock_qwiic_mod.QwiicMMC5983MA.side_effect = RuntimeError("Init fail")

    with patch.dict(sys.modules, {'qwiic_mmc5983ma': mock_qwiic_mod}):
        with pytest.raises(DeviceControlException):
            MagSensorMmc5983maSF_I2C(
                {}, "MMC_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x30',
            )


# --- SGP40 ---

def test_sgp40_i2c():
    mock_board = MagicMock()
    mock_sgp_mod = MagicMock()
    mock_dev = MagicMock()
    mock_sgp_mod.SGP40.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_sgp40': mock_sgp_mod}):
        sensor = VocSensorSgp40_I2C(
            {}, "SGP_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x59',
        )
        mock_dev.raw = 28500
        assert sensor.update()['data'] == (28500,)

        type(mock_dev).raw = PropertyMock(side_effect=RuntimeError("Bus err"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(mock_dev).raw = PropertyMock(side_effect=TypeError("Type err"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_sgp40_init_exception():
    mock_board = MagicMock()
    mock_sgp_mod = MagicMock()
    mock_sgp_mod.SGP40.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_sgp40': mock_sgp_mod}):
        with pytest.raises(DeviceControlException):
            VocSensorSgp40_I2C(
                {}, "SGP_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x59',
            )
