from multiprocessing import Array
from unittest.mock import patch
import pytest

from indi_allsky.devices.dew_heaters.dewHeaterSimulator import DewHeaterSimulator
from indi_allsky.devices.fans.fanSimulator import FanSimulator
from indi_allsky.devices.focusers.focuserSimulator import FocuserSimulator
from indi_allsky.devices.generic.gpioSimulator import GpioSimulator
from indi_allsky.devices.sensors.sensorSimulator import SensorSimulator, SensorDataGenerator


def test_dew_heater_simulator():
    heater = DewHeaterSimulator({}, "DewHeaterSim", Array('i', [0]*10), Array('f', [0.0]*10))
    heater.state = 50
    assert heater.state == 0
    heater.disable()
    assert heater.state == 0


def test_fan_simulator():
    fan = FanSimulator({}, "FanSim", Array('i', [0]*10), Array('f', [0.0]*10))
    fan.state = 80
    assert fan.state == 0
    fan.disable()
    assert fan.state == 0


def test_focuser_simulator():
    focuser = FocuserSimulator({}, "FocuserSim", Array('i', [0]*10), Array('f', [0.0]*10))
    with patch('time.sleep', return_value=None):
        steps_cw = focuser.move('cw', 100)
        assert steps_cw == 100

        steps_ccw = focuser.move('ccw', 50)
        assert steps_ccw == -50


def test_gpio_simulator():
    gpio = GpioSimulator({}, "GpioSim", Array('i', [0]*10), Array('f', [0.0]*10))
    gpio.state = 1
    assert gpio.state == 0
    gpio.disable()
    assert gpio.state == 0


def test_sensor_simulator_and_data_generator():
    sensor_sim = SensorSimulator({}, "SimSensor", Array('i', [0]*10), Array('f', [0.0]*10))
    res = sensor_sim.update()
    assert res == {'data': tuple()}

    data_gen = SensorDataGenerator({}, "DataGenSensor", Array('i', [0]*10), Array('f', [0.0]*10))
    res_gen = data_gen.update()
    assert 'data' in res_gen
    assert len(res_gen['data']) == 7
