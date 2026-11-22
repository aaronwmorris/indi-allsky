import sys
from multiprocessing import Array
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from indi_allsky.devices.exceptions import SensorReadException, DeviceControlException
from indi_allsky.devices.sensors.currentSensorIna219 import CurrentSensorIna219, CurrentSensorIna219_I2C
from indi_allsky.devices.sensors.currentSensorIna228 import CurrentSensorIna228, CurrentSensorIna228_I2C
from indi_allsky.devices.sensors.currentSensorIna23x import CurrentSensorIna23x, CurrentSensorIna23x_I2C
from indi_allsky.devices.sensors.currentSensorIna260 import CurrentSensorIna260, CurrentSensorIna260_I2C
from indi_allsky.devices.sensors.currentSensorIna3221 import CurrentSensorIna3221, CurrentSensorIna3221_I2C
from indi_allsky.devices.sensors.upsHatWaveshareE import UpsHatWaveshareE_MCU_I2C


# --- INA219 ---

def test_ina219_i2c_init_and_update():
    mock_board = MagicMock()
    mock_ina219_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ina219_mod.INA219.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina219': mock_ina219_mod}):
        sensor = CurrentSensorIna219_I2C(
            {}, "INA219_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x40',
        )
        assert sensor.name == "INA219_Test"
        assert sensor.ina219 == mock_dev

        # Test update
        mock_dev.bus_voltage = 12.0
        mock_dev.shunt_voltage = 0.05
        mock_dev.current = 1500.0  # mA -> 1.5 A
        mock_dev.power = 18.0  # W

        data = sensor.update()
        assert 'data' in data
        assert data['data'] == (12.05, 1.5, 18.0)

        # Test update RuntimeError
        type(mock_dev).bus_voltage = PropertyMock(side_effect=RuntimeError("I2C read error"))
        with pytest.raises(SensorReadException):
            sensor.update()
        type(mock_dev).bus_voltage = PropertyMock(return_value=12.0)


def test_ina219_i2c_init_exception():
    mock_board = MagicMock()
    mock_ina219_mod = MagicMock()
    mock_ina219_mod.INA219.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina219': mock_ina219_mod}):
        with pytest.raises(DeviceControlException):
            CurrentSensorIna219_I2C(
                {}, "INA219_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x40',
            )


# --- INA228 ---

def test_ina228_i2c_init_and_update():
    mock_board = MagicMock()
    mock_ina228_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ina228_mod.INA228.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina228': mock_ina228_mod}):
        # Celsius
        sensor_c = CurrentSensorIna228_I2C(
            {'TEMP_DISPLAY': 'c'}, "INA228_C", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x45',
        )
        mock_dev.bus_voltage = 5.0
        mock_dev.shunt_voltage = 0.01
        mock_dev.current = 500.0  # mA -> 0.5 A
        mock_dev.power = 2500.0   # mW -> 2.5 W
        mock_dev.die_temperature = 25.0

        data_c = sensor_c.update()
        assert data_c['data'] == (5.0, 0.5, 2.5, 25.0)

        # Fahrenheit
        sensor_f = CurrentSensorIna228_I2C(
            {'TEMP_DISPLAY': 'f'}, "INA228_F", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x45',
        )
        data_f = sensor_f.update()
        assert data_f['data'][3] == 77.0  # 25C = 77F

        # Kelvin
        sensor_k = CurrentSensorIna228_I2C(
            {'TEMP_DISPLAY': 'k'}, "INA228_K", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x45',
        )
        data_k = sensor_k.update()
        assert data_k['data'][3] == pytest.approx(298.15)

        # Error
        type(mock_dev).bus_voltage = PropertyMock(side_effect=RuntimeError("Bus error"))
        with pytest.raises(SensorReadException):
            sensor_c.update()
        type(mock_dev).bus_voltage = PropertyMock(return_value=5.0)


def test_ina228_i2c_init_exception():
    mock_board = MagicMock()
    mock_ina228_mod = MagicMock()
    mock_ina228_mod.INA228.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina228': mock_ina228_mod}):
        with pytest.raises(DeviceControlException):
            CurrentSensorIna228_I2C(
                {}, "INA228_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x45',
            )


# --- INA23x ---

def test_ina23x_i2c_init_and_update():
    mock_board = MagicMock()
    mock_ina23x_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ina23x_mod.INA23X.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina23x': mock_ina23x_mod}):
        sensor = CurrentSensorIna23x_I2C(
            {'TEMP_DISPLAY': 'c'}, "INA23X_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x48',
        )
        mock_dev.bus_voltage = 3.3
        mock_dev.shunt_voltage = 0.002
        mock_dev.current = 0.2  # A
        mock_dev.power = 0.66   # W
        mock_dev.die_temperature = 22.0

        data = sensor.update()
        assert data['data'] == (3.3, 0.2, 0.66, 22.0)

        # Test F and K branches
        sensor.config['TEMP_DISPLAY'] = 'f'
        assert sensor.update()['data'][3] == pytest.approx(71.6)
        sensor.config['TEMP_DISPLAY'] = 'k'
        assert sensor.update()['data'][3] == pytest.approx(295.15)

        # Error
        type(mock_dev).bus_voltage = PropertyMock(side_effect=RuntimeError("Bus error"))
        with pytest.raises(SensorReadException):
            sensor.update()
        type(mock_dev).bus_voltage = PropertyMock(return_value=3.3)


def test_ina23x_i2c_init_exception():
    mock_board = MagicMock()
    mock_ina23x_mod = MagicMock()
    mock_ina23x_mod.INA23X.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina23x': mock_ina23x_mod}):
        with pytest.raises(DeviceControlException):
            CurrentSensorIna23x_I2C(
                {}, "INA23X_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x48',
            )


# --- INA260 ---

def test_ina260_i2c_init_and_update():
    mock_board = MagicMock()
    mock_ina260_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ina260_mod.INA260.return_value = mock_dev

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina260': mock_ina260_mod}):
        sensor = CurrentSensorIna260_I2C(
            {}, "INA260_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x40',
        )
        mock_dev.voltage = 12.0
        mock_dev.current = 2000.0  # mA -> 2.0 A
        mock_dev.power = 24000.0   # mW -> 24.0 W

        data = sensor.update()
        assert data['data'] == (12.0, 2.0, 24.0)

        # Error
        type(mock_dev).voltage = PropertyMock(side_effect=RuntimeError("Read error"))
        with pytest.raises(SensorReadException):
            sensor.update()
        type(mock_dev).voltage = PropertyMock(return_value=12.0)


def test_ina260_i2c_init_exception():
    mock_board = MagicMock()
    mock_ina260_mod = MagicMock()
    mock_ina260_mod.INA260.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina260': mock_ina260_mod}):
        with pytest.raises(DeviceControlException):
            CurrentSensorIna260_I2C(
                {}, "INA260_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x40',
            )


# --- INA3221 ---

def test_ina3221_i2c_init_and_update():
    mock_board = MagicMock()
    mock_ina3221_mod = MagicMock()
    mock_dev = MagicMock()
    mock_ina3221_mod.INA3221.return_value = mock_dev

    # Mock 3 channels
    ch0 = MagicMock(shunt_voltage=0.01, bus_voltage=5.0, current=0.001)  # 0.001 * 1000 = 1.0 A
    ch1 = MagicMock(shunt_voltage=float('nan'), bus_voltage=0.0, current=0.0)  # NaN shunt
    ch2 = MagicMock(shunt_voltage=0.02, bus_voltage=12.0, current=0.002) # 0.002 * 1000 = 2.0 A
    mock_dev.__getitem__.side_effect = lambda idx: [ch0, ch1, ch2][idx]

    config = {
        'TEMP_SENSOR': {
            'INA3221_CH1_ENABLE': True,
            'INA3221_CH2_ENABLE': True,
            'INA3221_CH3_ENABLE': True,
        }
    }

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina3221': mock_ina3221_mod}):
        sensor = CurrentSensorIna3221_I2C(
            config, "INA3221_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x40',
        )
        assert sensor.ina3221_channels == [0, 1, 2]

        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 9
        # Channel 0
        assert data['data'][0] == 5.0
        assert data['data'][1] == 1.0
        assert data['data'][2] == 5.0
        # Channel 1 (NaN shunt returns -1.0)
        assert data['data'][3] == -1.0
        assert data['data'][4] == -1.0
        assert data['data'][5] == -1.0
        # Channel 2
        assert data['data'][6] == 12.0
        assert data['data'][7] == 2.0
        assert data['data'][8] == 24.0

        # Exception handling
        type(ch0).bus_voltage = PropertyMock(side_effect=RuntimeError("Channel error"))
        with pytest.raises(SensorReadException):
            sensor.update()

        type(ch0).bus_voltage = PropertyMock(side_effect=TypeError("Type error"))
        with pytest.raises(SensorReadException):
            sensor.update()
        type(ch0).bus_voltage = PropertyMock(return_value=5.0)


def test_ina3221_i2c_init_exception():
    mock_board = MagicMock()
    mock_ina3221_mod = MagicMock()
    mock_ina3221_mod.INA3221.side_effect = RuntimeError("Init failed")

    with patch.dict(sys.modules, {'board': mock_board, 'adafruit_ina3221': mock_ina3221_mod}):
        with pytest.raises(DeviceControlException):
            CurrentSensorIna3221_I2C(
                {}, "INA3221_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x40',
            )


# --- Waveshare UPS Hat (E) ---

def test_ups_hat_waveshare_e():
    mock_board = MagicMock()
    mock_i2c_dev_mod = MagicMock()
    mock_bus_dev = MagicMock()
    mock_bus_dev.i2c_device = mock_i2c_dev_mod

    mock_i2c_device_cls = MagicMock()
    mock_i2c_dev_mod.I2CDevice = mock_i2c_device_cls
    mock_device = MagicMock()
    mock_device.__enter__.return_value = mock_device
    mock_i2c_device_cls.return_value = mock_device

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bus_device': mock_bus_dev,
        'adafruit_bus_device.i2c_device': mock_i2c_dev_mod,
    }):
        sensor = UpsHatWaveshareE_MCU_I2C(
            {}, "UPS_Test", Array('i', [0]*10), Array('f', [0.0]*10),
            i2c_address='0x2d',
        )

        def fake_write_then_readinto(out_buf, in_buf, out_end=1):
            reg = out_buf[0]
            if reg == 0x02:  # Status (BIT_FAST = 0x40)
                in_buf[0] = 0x40
            elif reg == 0x10:  # VBUS (mV=5000, mA=1000, mW=5000)
                # 5000 = 0x1388 -> [0x88, 0x13], 1000 = 0x03E8 -> [0xE8, 0x03]
                in_buf[0:6] = bytearray([0x88, 0x13, 0xE8, 0x03, 0x88, 0x13])
            elif reg == 0x20:  # Battery (bat_mv=8000, bat_ma=-500 (signed 0xFE0C), bat_pct=95, rem=2500, tte=120, ttf=0)
                # 8000 = 0x1F40, -500 = 0xFE0C, 95 = 0x005F, 2500 = 0x09C4, 120 = 0x0078, 0 = 0x0000
                in_buf[0:12] = bytearray([
                    0x40, 0x1F,
                    0x0C, 0xFE,
                    0x5F, 0x00,
                    0xC4, 0x09,
                    0x78, 0x00,
                    0x00, 0x00,
                ])
            elif reg == 0x30:  # Cells (4000, 4000, 0, 0)
                # 4000 = 0x0FA0 -> [0xA0, 0x0F]
                in_buf[0:8] = bytearray([
                    0xA0, 0x0F,
                    0xA0, 0x0F,
                    0x00, 0x00,
                    0x00, 0x00,
                ])

        mock_device.write_then_readinto.side_effect = fake_write_then_readinto

        data = sensor.update()
        assert 'data' in data
        assert len(data['data']) == 14
        assert data['data'][0] == 3.0  # BIT_FAST
        assert data['data'][1] == 5000.0  # VBUS mV
        assert data['data'][2] == 1000.0  # VBUS mA
        assert data['data'][3] == 5000.0  # VBUS mW
        assert data['data'][4] == 8000.0  # Battery mV
        assert data['data'][5] == -500.0  # Battery mA (signed negative)
        assert data['data'][6] == 95.0    # Battery %
        assert data['data'][7] == 2500.0  # Remaining mAh
        assert data['data'][8] == 120.0   # Time to empty min
        assert data['data'][9] == 0.0     # Time to full min
        assert data['data'][10] == 4000.0 # Cell 1
        assert data['data'][11] == 4000.0 # Cell 2
        assert data['data'][12] == 0.0    # Cell 3
        assert data['data'][13] == 0.0    # Cell 4

        # Test other status bits: BIT_CHG, BIT_DIS, IDLE
        def status_chg(out_buf, in_buf, out_end=1):
            if out_buf[0] == 0x02:
                in_buf[0] = 0x80  # BIT_CHG
            else:
                fake_write_then_readinto(out_buf, in_buf, out_end)
        mock_device.write_then_readinto.side_effect = status_chg
        assert sensor.update()['data'][0] == 2.0

        def status_dis(out_buf, in_buf, out_end=1):
            if out_buf[0] == 0x02:
                in_buf[0] = 0x20  # BIT_DIS
            else:
                fake_write_then_readinto(out_buf, in_buf, out_end)
        mock_device.write_then_readinto.side_effect = status_dis
        assert sensor.update()['data'][0] == 1.0

        def status_idle(out_buf, in_buf, out_end=1):
            if out_buf[0] == 0x02:
                in_buf[0] = 0x00  # idle
            else:
                fake_write_then_readinto(out_buf, in_buf, out_end)
        mock_device.write_then_readinto.side_effect = status_idle
        assert sensor.update()['data'][0] == 0.0

        # Test read error
        mock_device.write_then_readinto.side_effect = OSError("I2C failure")
        with pytest.raises(SensorReadException):
            sensor.update()


def test_ups_hat_waveshare_e_init_exception():
    mock_board = MagicMock()
    mock_i2c_dev_mod = MagicMock()
    mock_bus_dev = MagicMock()
    mock_bus_dev.i2c_device = mock_i2c_dev_mod

    mock_i2c_device_cls = MagicMock(side_effect=RuntimeError("Bus Device Init Failed"))
    mock_i2c_dev_mod.I2CDevice = mock_i2c_device_cls

    with patch.dict(sys.modules, {
        'board': mock_board,
        'adafruit_bus_device': mock_bus_dev,
        'adafruit_bus_device.i2c_device': mock_i2c_dev_mod,
    }):
        with pytest.raises(DeviceControlException):
            UpsHatWaveshareE_MCU_I2C(
                {}, "UPS_Fail", Array('i', [0]*10), Array('f', [0.0]*10),
                i2c_address='0x2d',
            )

