import pytest
from multiprocessing import Array
from indi_allsky.devices.sensors.sensorBase import SensorBase
from indi_allsky.utils import IndiAllSkyDateCalcs
from indi_allsky import constants


class DummySensor(SensorBase):
    def update(self):
        pass


def test_temperature_conversions():
    sensor = DummySensor({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))
    # 0 C = 32 F, 100 C = 212 F
    assert sensor.c2f(0.0) == 32.0
    assert sensor.c2f(100.0) == 212.0
    assert sensor.f2c(32.0) == 0.0
    assert sensor.f2c(212.0) == 100.0


def test_dew_point_calculation():
    sensor = DummySensor({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))
    # At 20°C and 50% relative humidity, dew point is ~9.3°C
    dp = sensor.get_dew_point_c(20.0, 50.0)
    assert round(dp, 1) == 9.3

    # At 100% RH, dew point equals air temp
    dp_100 = sensor.get_dew_point_c(15.0, 100.0)
    assert round(dp_100, 1) == 15.0


def test_frost_point_calculation():
    sensor = DummySensor({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))
    # Test frost point when dew point is below 0°C
    fp = sensor.get_frost_point_c(-5.0, -10.0)
    assert isinstance(fp, float)
    assert fp < 0.0


def test_heat_index_calculation():
    sensor = DummySensor({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))
    # At 30°C (86°F) and 80% RH, heat index should be higher than ambient temp
    hi_c = sensor.get_heat_index_c(30.0, 80.0)
    assert hi_c > 30.0


def test_speed_and_pressure_conversions():
    sensor = DummySensor({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))
    # 1 m/s = 3.6 km/h
    assert sensor.mps2kmph(10.0) == 36.0
    # 1000 mm to inches
    assert round(sensor.mm2in(25.4), 2) == 1.0
