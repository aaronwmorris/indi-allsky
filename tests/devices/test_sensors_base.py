import math
from multiprocessing import Array
import pytest

from indi_allsky.devices.sensors.sensorBase import SensorBase
from indi_allsky.devices.sensors.sensorSimulator import SensorSimulator, SensorDataGenerator


def test_sensor_base_properties():
    config = {
        'TEMP_SENSOR': {
            'LUX_MAGNITUDE_OFFSET': 25.5,
        }
    }
    night_av = Array('i', [0] * 10)
    astro_av = Array('f', [0.0] * 10)
    sensor = SensorBase(config, "BaseTest", night_av, astro_av)

    assert sensor.name == "BaseTest"
    assert sensor.config == config
    assert sensor.night_av == night_av
    assert sensor.astro_av == astro_av
    assert sensor._lux_magnitude_offset == 25.5

    assert sensor.get_labels(None) == ()

    # Properties
    assert sensor.night is None
    sensor.night = 1
    assert sensor.night is True

    assert sensor.astro_darkness is None
    sensor.astro_darkness = 1
    assert sensor.astro_darkness is True

    assert sensor.heater_available is False
    sensor.heater_available = True
    assert sensor.heater_available is True

    assert sensor.heater_on is False
    sensor.heater_on = True
    assert sensor.heater_on is True

    assert sensor.slot is None
    sensor.slot = "2"
    assert sensor.slot == 2

    sensor.deinit()

    with pytest.raises(Exception, match='Not implemented'):
        sensor.update()


def test_sensor_base_conversions():
    sensor = SensorBase({}, "Test", Array('i', [0]*10), Array('f', [0.0]*10))

    # Temperature
    assert sensor.c2f(0) == 32.0
    assert sensor.c2f(100) == 212.0
    assert sensor.f2c(32) == 0.0
    assert sensor.f2c(212) == 100.0
    assert sensor.c2k(0) == 273.15
    assert sensor.k2c(273.15) == 0.0
    assert sensor.f2k(32) == pytest.approx(273.15)

    # Pressure
    assert sensor.hPa2psi(1000) == pytest.approx(14.5037, abs=0.01)
    assert sensor.hPa2inHg(1013.25) == pytest.approx(29.92, abs=0.01)
    assert sensor.hPa2mmHg(1013.25) == pytest.approx(760.0, abs=0.1)

    assert sensor.inHg2mb(29.92) == pytest.approx(29.92 * 0.029529983071445)
    assert sensor.inHg2psi(1.0) == pytest.approx(14.5037744)
    assert sensor.inHg2hpa(1.0) == pytest.approx(33.86389)
    assert sensor.inHg2mmHg(1.0) == 25.4

    # Velocity / Distance
    assert sensor.mps2kmph(10) == 36.0
    assert sensor.kmph2miph(100) == pytest.approx(62.137, abs=0.01)
    assert sensor.km2mi(100) == pytest.approx(62.137, abs=0.01)
    assert sensor.mps2miph(10) == pytest.approx(22.37, abs=0.01)
    assert sensor.mps2knots(10) == pytest.approx(19.438, abs=0.01)
    assert sensor.mph2knots(10) == pytest.approx(8.689, abs=0.01)
    assert sensor.mph2kmph(10) == pytest.approx(16.0934, abs=0.01)
    assert sensor.mph2mps(10) == pytest.approx(4.4704, abs=0.01)

    # Length
    assert sensor.mm2in(25.4) == pytest.approx(1.0, abs=0.001)

    # Lux to Mag
    mag_total, raw_mag = sensor.lux2mag(10.0)
    assert raw_mag == pytest.approx(-2.5)
    assert mag_total == pytest.approx(26.0 - 2.5)

    # Lux <= 0 gives ValueError handled gracefully
    mag_err, raw_err = sensor.lux2mag(0.0)
    assert raw_err == 0.0
    assert mag_err == 26.0

    # Heat index, Frost point, Dew point
    hi_f = sensor.get_heat_index_f(80.0, 75.0)
    assert hi_f > 80.0

    hi_c = sensor.get_heat_index_c(26.0, 75.0)
    assert hi_c > 26.0

    dew_c = sensor.get_dew_point_c(20.0, 50.0)
    assert 5.0 < dew_c < 15.0

    frost_c = sensor.get_frost_point_c(10.0, dew_c)
    assert frost_c < dew_c


def test_sensor_simulator():
    sensor = SensorSimulator({}, "Sim", Array('i', [0]*10), Array('f', [0.0]*10))
    data = sensor.update()
    assert data == {'data': ()}


def test_sensor_data_generator():
    sensor = SensorDataGenerator({}, "Generator", Array('i', [0]*10), Array('f', [0.0]*10))
    assert sensor.METADATA['count'] == 7
    assert len(sensor.METADATA['labels']) == 7

    data = sensor.update()
    assert 'data' in data
    assert len(data['data']) == 7
    assert data['data'][0] == 1
    assert data['data'][1] == pytest.approx(9.7)

    # Test fibonacci overflow reset
    sensor.fib_2 = 2 ** 25
    data2 = sensor.update()
    assert sensor.fib_1 == 0
    assert sensor.fib_2 == 1
