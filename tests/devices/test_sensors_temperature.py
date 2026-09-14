import sys
from multiprocessing import Array
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from indi_allsky import constants
from indi_allsky.devices.exceptions import SensorReadException, DeviceControlException
from indi_allsky.devices.sensors.tempSensorAhtx0 import TempSensorAhtx0_I2C
from indi_allsky.devices.sensors.tempSensorBme280 import TempSensorBme280_I2C, TempSensorBme280_SPI
from indi_allsky.devices.sensors.tempSensorBme680 import TempSensorBme680_I2C, TempSensorBme680_SPI
from indi_allsky.devices.sensors.tempSensorBmp180 import TempSensorBmp180_I2C
from indi_allsky.devices.sensors.tempSensorBmp280 import TempSensorBmp280_I2C, TempSensorBmp280_SPI
from indi_allsky.devices.sensors.tempSensorBmp3xx import TempSensorBmp3xx_I2C, TempSensorBmp3xx_SPI
from indi_allsky.devices.sensors.tempSensorDht import TempSensorDht22, TempSensorDht21, TempSensorDht11
from indi_allsky.devices.sensors.tempSensorDs18x20 import TempSensorDs18x20
from indi_allsky.devices.sensors.tempSensorHdc302x import TempSensorHdc302x_I2C
from indi_allsky.devices.sensors.tempSensorHtu21d import TempSensorHtu21d_I2C
from indi_allsky.devices.sensors.tempSensorHtu31d import TempSensorHtu31d_I2C
from indi_allsky.devices.sensors.tempSensorLm35_Ads1x15 import (
    TempSensorLm35_Ads1015_I2C,
    TempSensorLm35_Ads1115_I2C,
)
from indi_allsky.devices.sensors.tempSensorTmp36_Ads1x15 import (
    TempSensorTmp36_Ads1015_I2C,
    TempSensorTmp36_Ads1115_I2C,
)
from indi_allsky.devices.sensors.tempSensorMlx90614 import TempSensorMlx90614_I2C
from indi_allsky.devices.sensors.tempSensorMlx90615 import TempSensorMlx90615_I2C
from indi_allsky.devices.sensors.tempSensorMlx90640 import TempSensorMlx90640_I2C
from indi_allsky.devices.sensors.tempSensorScd30 import TempSensorScd30_I2C
from indi_allsky.devices.sensors.tempSensorScd4x import TempSensorScd4x_I2C
from indi_allsky.devices.sensors.tempSensorSht3x import TempSensorSht3x_I2C
from indi_allsky.devices.sensors.tempSensorSht4x import TempSensorSht4x_I2C
from indi_allsky.devices.sensors.tempSensorSi7021 import TempSensorSi7021_I2C


@pytest.fixture(autouse=True)
def fast_sleep():
    with patch('time.sleep', return_value=None):
        yield


# --- AHTx0 ---

def test_ahtx0_i2c():
    mock_board = MagicMock()
    mock_aht_mod = MagicMock()
    mock_dev = MagicMock()
    mock_aht_mod.AHTx0.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ahtx0': mock_aht_mod}):
        sensor = TempSensorAhtx0_I2C(
            {'TEMP_DISPLAY': 'c'}, "AHT_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x38',
        )
        mock_dev.temperature = 21.0
        mock_dev.relative_humidity = 50.0

        data = sensor.update()
        assert data['data'][0] == 21.0
        assert data['data'][1] == 50.0

        # F and K
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == pytest.approx(69.8)
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(294.15)

        # ValueError in dew point
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("bad")):
            data_err = sensor.update()
            assert data_err['dew_point'] == 0.0

        # RuntimeError
        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Bus err"))
        with pytest.raises(SensorReadException):
            sensor.update()


def test_ahtx0_init_exception():
    mock_board = MagicMock()
    mock_aht_mod = MagicMock()
    mock_aht_mod.AHTx0.side_effect = RuntimeError("Init fail")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ahtx0': mock_aht_mod}):
        with pytest.raises(DeviceControlException):
            TempSensorAhtx0_I2C(
                {}, "AHT_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x38',
            )


# --- BME280 ---

def test_bme280_i2c_and_spi():
    mock_board = MagicMock()
    mock_board.D5 = 'D5'
    mock_bme_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bme_mod.Adafruit_BME280_I2C.return_value = mock_dev
    mock_bme_mod.Adafruit_BME280_SPI.return_value = mock_dev
    mock_digitalio = MagicMock()

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bme280': MagicMock(advanced=mock_bme_mod),
        'adafruit_bme280.advanced': mock_bme_mod,
        'digitalio': mock_digitalio,
    }):
        # I2C
        sensor_i2c = TempSensorBme280_I2C(
            {'TEMP_DISPLAY': 'c', 'PRESSURE_DISPLAY': 'hPa'},
            "BME280_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x76',
        )
        mock_dev.temperature = 20.0
        mock_dev.humidity = 40.0
        mock_dev.pressure = 1013.25

        data = sensor_i2c.update()
        assert data['data'][0] == 20.0
        assert data['data'][2] == 1013.25

        # Pressure conversions: psi, inHg, mmHg
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor_i2c.update()['data'][2] == pytest.approx(14.696, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor_i2c.update()['data'][2] == pytest.approx(29.92, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor_i2c.update()['data'][2] == pytest.approx(760.0, abs=0.5)

        # Temperature displays: f, k
        sensor_i2c.config['TEMP_DISPLAY'] = 'f'
        assert sensor_i2c.update()['data'][0] == 68.0
        sensor_i2c.config['TEMP_DISPLAY'] = 'k'
        assert sensor_i2c.update()['data'][0] == pytest.approx(293.15)

        # ValueError in dew point
        sensor_i2c.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor_i2c, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor_i2c.update()['dew_point'] == 0.0

        # Read exception
        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Read err"))
        with pytest.raises(SensorReadException):
            sensor_i2c.update()
        type(mock_dev).temperature = PropertyMock(return_value=20.0)

        # SPI
        sensor_spi = TempSensorBme280_SPI(
            {}, "BME280_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D5',
        )
        assert sensor_spi.bme280 == mock_dev

        # Init exceptions
        mock_bme_mod.Adafruit_BME280_I2C.side_effect = RuntimeError("I2C fail")
        with pytest.raises(DeviceControlException):
            TempSensorBme280_I2C(
                {}, "BME_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x76',
            )

        mock_bme_mod.Adafruit_BME280_SPI.side_effect = RuntimeError("SPI fail")
        with pytest.raises(DeviceControlException):
            TempSensorBme280_SPI(
                {}, "BME_SPI_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D5',
            )


# --- BME680 ---

def test_bme680_i2c_and_spi():
    mock_board = MagicMock()
    mock_board.D6 = 'D6'
    mock_bme_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bme_mod.Adafruit_BME680_I2C.return_value = mock_dev
    mock_bme_mod.Adafruit_BME680_SPI.return_value = mock_dev
    mock_digitalio = MagicMock()

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bme680': mock_bme_mod,
        'digitalio': mock_digitalio,
    }):
        sensor_i2c = TempSensorBme680_I2C(
            {'TEMP_DISPLAY': 'c', 'PRESSURE_DISPLAY': 'hPa'},
            "BME680_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x77',
        )
        mock_dev.temperature = 22.0
        mock_dev.humidity = 45.0
        mock_dev.pressure = 1015.0
        mock_dev.gas = 12000

        data = sensor_i2c.update()
        assert data['data'][0] == 22.0
        assert data['data'][2] == 1015.0
        assert data['data'][3] == 12000

        # Pressure conversions: psi, inHg, mmHg
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor_i2c.update()['data'][2] == pytest.approx(14.72, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor_i2c.update()['data'][2] == pytest.approx(29.97, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor_i2c.update()['data'][2] == pytest.approx(761.3, abs=0.5)

        # Temperature: k
        sensor_i2c.config['TEMP_DISPLAY'] = 'k'
        assert sensor_i2c.update()['data'][0] == pytest.approx(295.15)

        # ValueError in dew point
        sensor_i2c.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor_i2c, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor_i2c.update()['dew_point'] == 0.0

        # Read exception
        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Read err"))
        with pytest.raises(SensorReadException):
            sensor_i2c.update()
        type(mock_dev).temperature = PropertyMock(return_value=22.0)

        # SPI
        sensor_spi = TempSensorBme680_SPI(
            {}, "BME680_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D6',
        )
        assert sensor_spi.bme680 == mock_dev

        # Init exceptions
        mock_bme_mod.Adafruit_BME680_I2C.side_effect = RuntimeError("I2C fail")
        with pytest.raises(DeviceControlException):
            TempSensorBme680_I2C(
                {}, "BME_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x77',
            )

        mock_bme_mod.Adafruit_BME680_SPI.side_effect = RuntimeError("SPI fail")
        with pytest.raises(DeviceControlException):
            TempSensorBme680_SPI(
                {}, "BME_SPI_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D6',
            )


# --- BMP180 ---

def test_bmp180_i2c():
    mock_board = MagicMock()
    mock_bmp180_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bmp180_mod.BMP180.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'bmp180': mock_bmp180_mod}):
        sensor = TempSensorBmp180_I2C(
            {'TEMP_DISPLAY': 'c', 'PRESSURE_DISPLAY': 'hPa'},
            "BMP180_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x77',
        )
        mock_dev.temperature = 19.5
        mock_dev.pressure = 1012.0

        data = sensor.update()
        assert data['data'] == (19.5, 1012.0)

        # Pressure conversions & temp display
        sensor.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor.update()['data'][1] == pytest.approx(14.678, abs=0.01)
        sensor.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor.update()['data'][1] == pytest.approx(29.88, abs=0.01)
        sensor.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor.update()['data'][1] == pytest.approx(759.0, abs=0.5)

        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == pytest.approx(67.1)
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(292.65)

        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor.update()

        # Init exception
        mock_bmp180_mod.BMP180.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorBmp180_I2C(
                {}, "BMP_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x77',
            )


# --- BMP280 ---

def test_bmp280_i2c_and_spi():
    mock_board = MagicMock()
    mock_board.D7 = 'D7'
    mock_bmp280_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bmp280_mod.Adafruit_BMP280_I2C.return_value = mock_dev
    mock_bmp280_mod.Adafruit_BMP280_SPI.return_value = mock_dev
    mock_digitalio = MagicMock()

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bmp280': mock_bmp280_mod,
        'digitalio': mock_digitalio,
    }):
        sensor_i2c = TempSensorBmp280_I2C(
            {'TEMP_DISPLAY': 'c', 'PRESSURE_DISPLAY': 'hPa'},
            "BMP280_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x76',
        )
        mock_dev.temperature = 25.0
        mock_dev.pressure = 1005.0

        data = sensor_i2c.update()
        assert data['data'] == (25.0, 1005.0)

        # Pressure & Temp displays
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor_i2c.update()['data'][1] == pytest.approx(14.576, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor_i2c.update()['data'][1] == pytest.approx(29.677, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor_i2c.update()['data'][1] == pytest.approx(753.8, abs=0.5)

        sensor_i2c.config['TEMP_DISPLAY'] = 'f'
        assert sensor_i2c.update()['data'][0] == 77.0
        sensor_i2c.config['TEMP_DISPLAY'] = 'k'
        assert sensor_i2c.update()['data'][0] == pytest.approx(298.15)

        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor_i2c.update()
        type(mock_dev).temperature = PropertyMock(return_value=25.0)

        # SPI
        sensor_spi = TempSensorBmp280_SPI(
            {}, "BMP280_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D7',
        )
        assert sensor_spi.bmp280 == mock_dev

        # Init exceptions
        mock_bmp280_mod.Adafruit_BMP280_I2C.side_effect = RuntimeError("I2C fail")
        with pytest.raises(DeviceControlException):
            TempSensorBmp280_I2C(
                {}, "BMP_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x76',
            )

        mock_bmp280_mod.Adafruit_BMP280_SPI.side_effect = RuntimeError("SPI fail")
        with pytest.raises(DeviceControlException):
            TempSensorBmp280_SPI(
                {}, "BMP_SPI_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D7',
            )


# --- BMP3xx ---

def test_bmp3xx_i2c_and_spi():
    mock_board = MagicMock()
    mock_board.D8 = 'D8'
    mock_bmp3xx_mod = MagicMock()
    mock_dev = MagicMock()
    mock_bmp3xx_mod.BMP3XX_I2C.return_value = mock_dev
    mock_bmp3xx_mod.BMP3xx_SPI.return_value = mock_dev
    mock_digitalio = MagicMock()

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bmp3xx': mock_bmp3xx_mod,
        'digitalio': mock_digitalio,
    }):
        sensor_i2c = TempSensorBmp3xx_I2C(
            {'TEMP_DISPLAY': 'c', 'PRESSURE_DISPLAY': 'hPa'},
            "BMP3XX_I2C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x77',
        )
        mock_dev.temperature = 23.0
        mock_dev.pressure = 1010.0

        data = sensor_i2c.update()
        assert data['data'] == (23.0, 1010.0)

        # Pressure & Temp displays
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'psi'
        assert sensor_i2c.update()['data'][1] == pytest.approx(14.648, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'inHg'
        assert sensor_i2c.update()['data'][1] == pytest.approx(29.825, abs=0.01)
        sensor_i2c.config['PRESSURE_DISPLAY'] = 'mmHg'
        assert sensor_i2c.update()['data'][1] == pytest.approx(757.5, abs=0.5)

        sensor_i2c.config['TEMP_DISPLAY'] = 'f'
        assert sensor_i2c.update()['data'][0] == pytest.approx(73.4)
        sensor_i2c.config['TEMP_DISPLAY'] = 'k'
        assert sensor_i2c.update()['data'][0] == pytest.approx(296.15)

        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor_i2c.update()
        type(mock_dev).temperature = PropertyMock(return_value=23.0)

        # SPI
        sensor_spi = TempSensorBmp3xx_SPI(
            {}, "BMP3XX_SPI", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D8',
        )
        assert sensor_spi.bmp3xx == mock_dev

        # Init exceptions
        mock_bmp3xx_mod.BMP3XX_I2C.side_effect = RuntimeError("I2C fail")
        with pytest.raises(DeviceControlException):
            TempSensorBmp3xx_I2C(
                {}, "BMP_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x77',
            )

        mock_bmp3xx_mod.BMP3xx_SPI.side_effect = RuntimeError("SPI fail")
        with pytest.raises(DeviceControlException):
            TempSensorBmp3xx_SPI(
                {}, "BMP_SPI_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                pin_1_name='D8',
            )


# --- DHT (DHT22, DHT21, DHT11) ---

def test_dht_sensors():
    mock_board = MagicMock()
    mock_board.D4 = 'D4'
    mock_dht_mod = MagicMock()
    mock_dev = MagicMock()
    mock_dht_mod.DHT22.return_value = mock_dev
    mock_dht_mod.DHT21.return_value = mock_dev
    mock_dht_mod.DHT11.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_dht': mock_dht_mod}):
        # DHT22
        dht22 = TempSensorDht22(
            {'TEMP_DISPLAY': 'c'}, "DHT22_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D4',
        )
        mock_dev.temperature = 22.0
        mock_dev.humidity = 55.0

        data = dht22.update()
        assert data['data'][0] == 22.0
        assert data['data'][1] == 55.0

        # Temp display
        dht22.config['TEMP_DISPLAY'] = 'f'
        assert dht22.update()['data'][0] == pytest.approx(71.6)
        dht22.config['TEMP_DISPLAY'] = 'k'
        assert dht22.update()['data'][0] == pytest.approx(295.15)

        # ValueError in dew point
        dht22.config['TEMP_DISPLAY'] = 'c'
        with patch.object(dht22, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert dht22.update()['dew_point'] == 0.0

        # Errors: RuntimeError & OverflowError
        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Checksum err"))
        with pytest.raises(SensorReadException):
            dht22.update()

        type(mock_dev).temperature = PropertyMock(side_effect=OverflowError("Overflow"))
        with pytest.raises(SensorReadException):
            dht22.update()
        type(mock_dev).temperature = PropertyMock(return_value=22.0)

        # DHT21 & DHT11
        dht21 = TempSensorDht21(
            {}, "DHT21_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D4',
        )
        assert dht21.dht == mock_dev

        dht11 = TempSensorDht11(
            {}, "DHT11_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            pin_1_name='D4',
        )
        assert dht11.dht == mock_dev

        # Init exceptions
        mock_dht_mod.DHT22.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorDht22({}, "DHT_Fail", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='D4')

        mock_dht_mod.DHT21.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorDht21({}, "DHT_Fail", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='D4')

        mock_dht_mod.DHT11.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorDht11({}, "DHT_Fail", Array('i', [0]*10), Array('f', [0.0]*10), pin_1_name='D4')


# --- DS18x20 (1-wire) ---

def test_ds18x20(tmp_path):
    w1_dir = tmp_path / "w1" / "devices"
    dev_folder = w1_dir / "28-000001234567"
    dev_folder.mkdir(parents=True)
    temp_file = dev_folder / "temperature"
    temp_file.write_text("24500\n")

    dev_folder2 = w1_dir / "28-000009999999"
    dev_folder2.mkdir(parents=True)
    (dev_folder2 / "temperature").write_text("24500\n")

    with patch('indi_allsky.devices.sensors.tempSensorDs18x20.Path') as mock_path_cls:
        mock_path_cls.side_effect = lambda p: tmp_path / p.lstrip('/') if isinstance(p, str) else p
        # Test normal init & update
        with patch('indi_allsky.devices.sensors.tempSensorDs18x20.Path') as p_cls:
            p_cls.return_value = w1_dir
            sensor = TempSensorDs18x20(
                {'TEMP_DISPLAY': 'c'}, "DS18_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            )
            data = sensor.update()
            assert data['data'] == (24.5,)

            # Temp displays
            sensor.config['TEMP_DISPLAY'] = 'f'
            assert sensor.update()['data'][0] == pytest.approx(76.1)
            sensor.config['TEMP_DISPLAY'] = 'k'
            assert sensor.update()['data'][0] == pytest.approx(297.65)

            # ValueError & RuntimeError in update
            sensor.ds_temp_file.write_text("bad_number\n")
            with pytest.raises(SensorReadException):
                sensor.update()

            with patch('builtins.int', side_effect=RuntimeError("Bus glitch")):
                with pytest.raises(SensorReadException):
                    sensor.update()


def test_ds18x20_init_errors(tmp_path):
    # 1-Wire not enabled
    nonexistent = tmp_path / "nonexistent"
    with patch('indi_allsky.devices.sensors.tempSensorDs18x20.Path', return_value=nonexistent):
        with pytest.raises(Exception, match='1-Wire interface is not enabled'):
            TempSensorDs18x20({}, "DS18", Array('i', [0]*10), Array('f', [0.0]*10))

    # Device not found
    empty_w1 = tmp_path / "empty_w1"
    empty_w1.mkdir()
    with patch('indi_allsky.devices.sensors.tempSensorDs18x20.Path', return_value=empty_w1):
        with pytest.raises(Exception, match='DS18x20 device not found'):
            TempSensorDs18x20({}, "DS18", Array('i', [0]*10), Array('f', [0.0]*10))

    # Temperature file missing
    dev_folder = empty_w1 / "28-12345"
    dev_folder.mkdir()
    with patch('indi_allsky.devices.sensors.tempSensorDs18x20.Path', return_value=empty_w1):
        with pytest.raises(Exception, match='temperature property not found'):
            TempSensorDs18x20({}, "DS18", Array('i', [0]*10), Array('f', [0.0]*10))


# --- HDC302x ---

def test_hdc302x_i2c():
    mock_board = MagicMock()
    mock_hdc_mod = MagicMock()
    mock_dev = MagicMock()
    mock_hdc_mod.HDC302x.return_value = mock_dev

    night_av = Array('i', [0]*10)
    night_av[constants.NIGHT_NIGHT] = 0  # Day

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_hdc302x': mock_hdc_mod}):
        sensor = TempSensorHdc302x_I2C(
            {'TEMP_DISPLAY': 'c'}, "HDC_Test", night_av, Array('f', [0.0]*10),
            i2c_address='0x44',
        )
        mock_dev.temperature = 20.0
        mock_dev.relative_humidity = 60.0

        data_day = sensor.update()
        assert data_day['data'][0] == 20.0
        assert mock_dev.heater == sensor.heater_day

        # Transition to night
        night_av[constants.NIGHT_NIGHT] = 1
        data_night = sensor.update()
        assert mock_dev.heater == sensor.heater_night

        # F and K
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][0] == 68.0
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][0] == pytest.approx(293.15)

        # ValueError in dew point
        sensor.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor.update()['dew_point'] == 0.0

        type(mock_dev).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor.update()

        # Init exception
        mock_hdc_mod.HDC302x.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorHdc302x_I2C(
                {}, "HDC_Fail", night_av, Array('f', [0.0]*10),
                i2c_address='0x44',
            )


# --- HTU21D & HTU31D ---

def test_htu21d_and_htu31d_i2c():
    mock_board = MagicMock()
    mock_htu21d_mod = MagicMock()
    mock_dev21 = MagicMock()
    mock_htu21d_mod.HTU21D.return_value = mock_dev21

    mock_htu31d_mod = MagicMock()
    mock_dev31 = MagicMock()
    mock_htu31d_mod.HTU31D.return_value = mock_dev31

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_htu21d': mock_htu21d_mod,
        'adafruit_htu31d': mock_htu31d_mod,
    }):
        # HTU21D
        sensor21 = TempSensorHtu21d_I2C(
            {'TEMP_DISPLAY': 'c'}, "HTU21_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x40',
        )
        mock_dev21.temperature = 22.5
        mock_dev21.relative_humidity = 48.0
        assert sensor21.update()['data'] == (22.5, 48.0, pytest.approx(11.0, abs=1.0))

        sensor21.config['TEMP_DISPLAY'] = 'f'
        assert sensor21.update()['data'][0] == pytest.approx(72.5)
        sensor21.config['TEMP_DISPLAY'] = 'k'
        assert sensor21.update()['data'][0] == pytest.approx(295.65)

        sensor21.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor21, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor21.update()['dew_point'] == 0.0

        type(mock_dev21).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor21.update()

        # HTU31D with heater checks
        night_av = Array('i', [0]*10)
        night_av[constants.NIGHT_NIGHT] = 0
        sensor31 = TempSensorHtu31d_I2C(
            {'TEMP_DISPLAY': 'c'}, "HTU31_Test", night_av, Array('f', [0.0]*10),
            i2c_address='0x41',
        )
        sensor31.heater_day = True
        sensor31.heater_night = True
        sensor31.heater_available = True

        mock_dev31.temperature = 24.0
        mock_dev31.relative_humidity = 85.0  # >= 80% enables heater
        sensor31.update()
        assert sensor31.heater_on is True

        mock_dev31.relative_humidity = 70.0  # <= 75% disables heater
        sensor31.update()
        assert sensor31.heater_on is False

        # Night toggle
        night_av[constants.NIGHT_NIGHT] = 1
        sensor31.update()

        # Temp displays
        sensor31.config['TEMP_DISPLAY'] = 'f'
        assert sensor31.update()['data'][0] == pytest.approx(75.2)
        sensor31.config['TEMP_DISPLAY'] = 'k'
        assert sensor31.update()['data'][0] == pytest.approx(297.15)

        sensor31.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor31, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor31.update()['dew_point'] == 0.0

        type(mock_dev31).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor31.update()

        # Init exceptions
        mock_htu21d_mod.HTU21D.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorHtu21d_I2C({}, "HTU21_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x40')

        mock_htu31d_mod.HTU31D.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorHtu31d_I2C({}, "HTU31_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x41')


# --- LM35 & TMP36 (via ADS1015 / ADS1115) ---

def test_lm35_and_tmp36_ads():
    mock_board = MagicMock()
    mock_ads1015 = MagicMock()
    mock_ads1115 = MagicMock()
    mock_analog_in = MagicMock()
    mock_ads1015.P0 = 'P0'
    mock_ads1115.P0 = 'P0'
    mock_sensor_pin = MagicMock()
    mock_analog_in.AnalogIn.return_value = mock_sensor_pin

    mock_ads_parent = MagicMock()
    mock_ads_parent.ads1015 = mock_ads1015
    mock_ads_parent.ads1115 = mock_ads1115
    mock_ads_parent.analog_in = mock_analog_in

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_ads1x15': mock_ads_parent,
        'adafruit_ads1x15.ads1015': mock_ads1015,
        'adafruit_ads1x15.ads1115': mock_ads1115,
        'adafruit_ads1x15.analog_in': mock_analog_in,
    }):
        # LM35 ADS1015: temp_c = voltage * 100
        mock_sensor_pin.voltage = 0.25  # 25.0 C
        lm35_1015 = TempSensorLm35_Ads1015_I2C(
            {'TEMP_DISPLAY': 'c'}, "LM35_1015", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x48', pin_1_name='P0',
        )
        assert lm35_1015.update()['data'] == (25.0,)

        lm35_1015.config['TEMP_DISPLAY'] = 'f'
        assert lm35_1015.update()['data'] == (77.0,)
        lm35_1015.config['TEMP_DISPLAY'] = 'k'
        assert lm35_1015.update()['data'] == (pytest.approx(298.15),)

        # LM35 ADS1115
        lm35_1115 = TempSensorLm35_Ads1115_I2C(
            {}, "LM35_1115", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x48', pin_1_name='P0',
        )
        assert lm35_1115.sensor == mock_sensor_pin

        # TMP36 ADS1015: temp_c = (voltage - 0.5) * 100
        mock_sensor_pin.voltage = 0.75  # (0.75 - 0.5) * 100 = 25.0 C
        tmp36_1015 = TempSensorTmp36_Ads1015_I2C(
            {'TEMP_DISPLAY': 'c'}, "TMP36_1015", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x48', pin_1_name='P0',
        )
        assert tmp36_1015.update()['data'] == (25.0,)

        tmp36_1015.config['TEMP_DISPLAY'] = 'f'
        assert tmp36_1015.update()['data'] == (77.0,)
        tmp36_1015.config['TEMP_DISPLAY'] = 'k'
        assert tmp36_1015.update()['data'] == (pytest.approx(298.15),)

        # TMP36 ADS1115
        tmp36_1115 = TempSensorTmp36_Ads1115_I2C(
            {}, "TMP36_1115", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x48', pin_1_name='P0',
        )
        assert tmp36_1115.sensor == mock_sensor_pin

        # Read error
        type(mock_sensor_pin).voltage = PropertyMock(side_effect=RuntimeError("ADC error"))
        with pytest.raises(SensorReadException):
            lm35_1015.update()
        with pytest.raises(SensorReadException):
            tmp36_1015.update()
        type(mock_sensor_pin).voltage = PropertyMock(return_value=0.25)

        # Init exceptions
        mock_ads1015.ADS1015.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorLm35_Ads1015_I2C({}, "LM_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x48', pin_1_name='P0')
        with pytest.raises(DeviceControlException):
            TempSensorTmp36_Ads1015_I2C({}, "TMP_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x48', pin_1_name='P0')

        mock_ads1115.ADS1115.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorLm35_Ads1115_I2C({}, "LM_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x48', pin_1_name='P0')
        with pytest.raises(DeviceControlException):
            TempSensorTmp36_Ads1115_I2C({}, "TMP_Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x48', pin_1_name='P0')


# --- MLX90614, MLX90615, MLX90640 ---

def test_mlx_sensors():
    mock_board = MagicMock()
    mock_mlx14_mod = MagicMock()
    mock_dev14 = MagicMock()
    mock_mlx14_mod.MLX90614.return_value = mock_dev14

    mock_mlx15_mod = MagicMock()
    mock_dev15 = MagicMock()
    mock_mlx15_mod.MLX90615.return_value = mock_dev15

    mock_mlx40_mod = MagicMock()
    mock_dev40 = MagicMock()
    mock_mlx40_mod.MLX90640.return_value = mock_dev40

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_mlx90614': mock_mlx14_mod,
        'aaronwmorris_mlx90615': mock_mlx15_mod,
        'adafruit_mlx90640': mock_mlx40_mod,
    }):
        # MLX90614
        sensor14 = TempSensorMlx90614_I2C(
            {'TEMP_DISPLAY': 'c'}, "MLX14", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x5a',
        )
        mock_dev14.ambient_temperature = 20.0
        mock_dev14.object_temperature = -10.0
        assert sensor14.update()['data'] == (20.0, -10.0)

        sensor14.config['TEMP_DISPLAY'] = 'f'
        assert sensor14.update()['data'] == (68.0, 14.0)
        sensor14.config['TEMP_DISPLAY'] = 'k'
        assert sensor14.update()['data'] == (pytest.approx(293.15), pytest.approx(263.15))

        type(mock_dev14).ambient_temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor14.update()

        # MLX90615
        sensor15 = TempSensorMlx90615_I2C(
            {'TEMP_DISPLAY': 'c'}, "MLX15", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x5b',
        )
        mock_dev15.ambient_temperature = 21.0
        mock_dev15.object_temperature = -5.0
        assert sensor15.update()['data'] == (21.0, -5.0)

        sensor15.config['TEMP_DISPLAY'] = 'f'
        assert sensor15.update()['data'] == (pytest.approx(69.8), 23.0)
        sensor15.config['TEMP_DISPLAY'] = 'k'
        assert sensor15.update()['data'] == (pytest.approx(294.15), pytest.approx(268.15))

        type(mock_dev15).ambient_temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor15.update()

        # MLX90640
        sensor40 = TempSensorMlx90640_I2C(
            {'TEMP_DISPLAY': 'c'}, "MLX40", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x33',
        )
        def fake_get_frame(frame):
            for i in range(len(frame)):
                frame[i] = 15.0
        mock_dev40.getFrame.side_effect = fake_get_frame
        assert sensor40.update()['data'] == (15.0,)

        sensor40.config['TEMP_DISPLAY'] = 'f'
        assert sensor40.update()['data'] == (59.0,)
        sensor40.config['TEMP_DISPLAY'] = 'k'
        assert sensor40.update()['data'] == (pytest.approx(288.15),)

        mock_dev40.getFrame.side_effect = RuntimeError("Frame error")
        with pytest.raises(SensorReadException):
            sensor40.update()

        mock_dev40.getFrame.side_effect = ValueError("Frame val error")
        with pytest.raises(SensorReadException):
            sensor40.update()

        # Init exceptions
        mock_mlx14_mod.MLX90614.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorMlx90614_I2C({}, "Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x5a')

        mock_mlx15_mod.MLX90615.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorMlx90615_I2C({}, "Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x5b')

        mock_mlx40_mod.MLX90640.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorMlx90640_I2C({}, "Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x33')


# --- SCD30 & SCD4x ---

def test_scd30_and_scd4x_i2c():
    mock_board = MagicMock()
    mock_scd30_mod = MagicMock()
    mock_dev30 = MagicMock()
    mock_scd30_mod.SCD30.return_value = mock_dev30

    mock_scd4x_mod = MagicMock()
    mock_dev4x = MagicMock()
    mock_scd4x_mod.SCD4x.return_value = mock_dev4x

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_scd30': mock_scd30_mod,
        'adafruit_scd4x': mock_scd4x_mod,
    }):
        # SCD30
        sensor30 = TempSensorScd30_I2C(
            {'TEMP_DISPLAY': 'c'}, "SCD30_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x61',
        )
        # Not ready
        mock_dev30.data_available = False
        sensor30.data = {'cached': True}
        assert sensor30.update() == {'cached': True}

        # Ready
        mock_dev30.data_available = True
        mock_dev30.temperature = 22.0
        mock_dev30.relative_humidity = 50.0
        mock_dev30.CO2 = 600.0

        data = sensor30.update()
        assert data['data'][0] == 22.0
        assert data['data'][1] == 50.0
        assert data['data'][2] == 600.0

        # Temp displays
        sensor30.config['TEMP_DISPLAY'] = 'f'
        assert sensor30.update()['data'][0] == pytest.approx(71.6)
        sensor30.config['TEMP_DISPLAY'] = 'k'
        assert sensor30.update()['data'][0] == pytest.approx(295.15)

        sensor30.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor30, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor30.update()['dew_point'] == 0.0

        type(mock_dev30).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor30.update()

        # SCD4x
        sensor4x = TempSensorScd4x_I2C(
            {'TEMP_DISPLAY': 'c'}, "SCD4X_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x62',
        )
        mock_dev4x.data_ready = False
        sensor4x.data = {'cached': True}
        assert sensor4x.update() == {'cached': True}

        mock_dev4x.data_ready = True
        mock_dev4x.temperature = 23.0
        mock_dev4x.relative_humidity = 45.0
        mock_dev4x.CO2 = 750.0

        data4 = sensor4x.update()
        assert data4['data'][0] == 23.0
        assert data4['data'][1] == 45.0
        assert data4['data'][2] == 750.0

        sensor4x.config['TEMP_DISPLAY'] = 'f'
        assert sensor4x.update()['data'][0] == pytest.approx(73.4)
        sensor4x.config['TEMP_DISPLAY'] = 'k'
        assert sensor4x.update()['data'][0] == pytest.approx(296.15)

        sensor4x.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor4x, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor4x.update()['dew_point'] == 0.0

        type(mock_dev4x).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor4x.update()

        # Init exceptions
        mock_scd30_mod.SCD30.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorScd30_I2C({}, "Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x61')

        mock_scd4x_mod.SCD4x.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorScd4x_I2C({}, "Fail", Array('i', [0]*10), Array('f', [0.0]*10), i2c_address='0x62')


# --- SHT3x, SHT4x, SI7021 ---

def test_sht3x_sht4x_si7021_i2c():
    mock_board = MagicMock()
    mock_sht3_mod = MagicMock()
    mock_dev3 = MagicMock()
    mock_sht3_mod.SHT31D.return_value = mock_dev3

    mock_sht4_mod = MagicMock()
    mock_dev4 = MagicMock()
    mock_sht4_mod.SHT4x.return_value = mock_dev4
    mock_sht4_mod.Mode.NOHEAT_HIGHPRECISION = 0x01

    mock_si7_mod = MagicMock()
    mock_dev7 = MagicMock()
    mock_si7_mod.SI7021.return_value = mock_dev7

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_sht31d': mock_sht3_mod,
        'adafruit_sht4x': mock_sht4_mod,
        'adafruit_si7021': mock_si7_mod,
    }):
        # SHT3x
        night_av = Array('i', [0]*10)
        night_av[constants.NIGHT_NIGHT] = 0
        sensor3 = TempSensorSht3x_I2C(
            {'TEMP_DISPLAY': 'c'}, "SHT3_Test", night_av, Array('f', [0.0]*10),
            i2c_address='0x44',
        )
        sensor3.heater_day = True
        sensor3.heater_night = True
        sensor3.heater_available = True

        mock_dev3.temperature = 22.0
        mock_dev3.relative_humidity = 82.0  # >= 80% enables heater
        sensor3.update()
        assert sensor3.heater_on is True

        mock_dev3.relative_humidity = 70.0  # <= 75% disables heater
        sensor3.update()
        assert sensor3.heater_on is False

        # Switch to night
        night_av[constants.NIGHT_NIGHT] = 1
        sensor3.update()

        sensor3.config['TEMP_DISPLAY'] = 'f'
        assert sensor3.update()['data'][0] == pytest.approx(71.6)
        sensor3.config['TEMP_DISPLAY'] = 'k'
        assert sensor3.update()['data'][0] == pytest.approx(295.15)

        sensor3.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor3, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor3.update()['dew_point'] == 0.0

        type(mock_dev3).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor3.update()

        # SHT4x
        sensor4 = TempSensorSht4x_I2C(
            {'TEMP_DISPLAY': 'c'}, "SHT4_Test", night_av, Array('f', [0.0]*10),
            i2c_address='0x44',
        )
        mock_dev4.measurements = (21.0, 50.0)

        assert sensor4.update()['data'][0] == 21.0
        night_av[constants.NIGHT_NIGHT] = 0
        sensor4.update()

        sensor4.config['TEMP_DISPLAY'] = 'f'
        assert sensor4.update()['data'][0] == pytest.approx(69.8)
        sensor4.config['TEMP_DISPLAY'] = 'k'
        assert sensor4.update()['data'][0] == pytest.approx(294.15)

        sensor4.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor4, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor4.update()['dew_point'] == 0.0

        type(mock_dev4).measurements = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor4.update()
        type(mock_dev4).measurements = PropertyMock(return_value=(21.0, 50.0))

        # SI7021
        sensor7 = TempSensorSi7021_I2C(
            {'TEMP_DISPLAY': 'c'}, "SI7_Test", night_av, Array('f', [0.0]*10),
            i2c_address='0x40',
        )
        sensor7.heater_level_day = 5
        sensor7.heater_level_night = -1

        mock_dev7.temperature = 23.5
        mock_dev7.relative_humidity = 45.0

        # Day mode with heater level 5
        night_av[constants.NIGHT_NIGHT] = 0
        sensor7.update()
        assert mock_dev7.heater_enable is True

        # Night mode with heater -1 (off)
        night_av[constants.NIGHT_NIGHT] = 1
        sensor7.update()
        assert mock_dev7.heater_enable is False

        # Night mode with heater >= 0
        sensor7.heater_level_night = 3
        sensor7.update_sensor_settings()
        assert mock_dev7.heater_enable is True

        # Day mode with heater < 0
        sensor7.night = False
        sensor7.heater_level_day = -1
        sensor7.update_sensor_settings()
        assert mock_dev7.heater_enable is False

        sensor7.config['TEMP_DISPLAY'] = 'f'
        assert sensor7.update()['data'][0] == pytest.approx(74.3)
        sensor7.config['TEMP_DISPLAY'] = 'k'
        assert sensor7.update()['data'][0] == pytest.approx(296.65)

        sensor7.config['TEMP_DISPLAY'] = 'c'
        with patch.object(sensor7, 'get_dew_point_c', side_effect=ValueError("bad")):
            assert sensor7.update()['dew_point'] == 0.0

        type(mock_dev7).temperature = PropertyMock(side_effect=RuntimeError("Err"))
        with pytest.raises(SensorReadException):
            sensor7.update()

        # Init exceptions
        mock_sht3_mod.SHT31D.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorSht3x_I2C({}, "Fail", night_av, Array('f', [0.0]*10), i2c_address='0x44')

        mock_sht4_mod.SHT4x.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorSht4x_I2C({}, "Fail", night_av, Array('f', [0.0]*10), i2c_address='0x44')

        mock_si7_mod.SI7021.side_effect = RuntimeError("Init fail")
        with pytest.raises(DeviceControlException):
            TempSensorSi7021_I2C({}, "Fail", night_av, Array('f', [0.0]*10), i2c_address='0x40')
