import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indi_allsky.devices.sensors import windSpeedSensorWhSpWs01 as wind_sensor
from indi_allsky.devices.exceptions import SensorException


@pytest.fixture
def gpio_backend(monkeypatch):
    device = Mock()
    factory = Mock(return_value=device)
    monkeypatch.setitem(sys.modules, 'board', SimpleNamespace(D25=SimpleNamespace(id=25)))
    monkeypatch.setitem(sys.modules, 'gpiozero', SimpleNamespace(DigitalInputDevice=factory))
    return device, factory


@pytest.mark.parametrize('units, expected', [
    ('ms', 10.0 / 3.0),
    ('kph', 12.0),
    ('mph', (10.0 / 3.0) * 2.2369362921),
    ('knots', (10.0 / 3.0) * 1.9438444924),
])
def test_pulse_count_and_units(gpio_backend, monkeypatch, units, expected):
    device, factory = gpio_backend
    clock = iter([100.0, 102.0, 104.0, 106.0])
    monkeypatch.setattr(wind_sensor.time, 'monotonic', lambda: next(clock))
    sensor = wind_sensor.WindSpeedSensorWhSpWs01(
        {'WINDSPEED_DISPLAY': units}, 'Wind', None, None, pin_1_name='D25',
    )
    factory.assert_called_once_with(25, pull_up=False)

    for pulse_index in range(10):
        device.when_activated()

    result = sensor.update()
    assert result['wind_speed'] == pytest.approx(expected, rel=1e-5)
    assert result['data'] == (result['wind_speed'],)
    assert sensor.update()['wind_speed'] == 0.0

    device.when_activated()
    assert sensor.update()['wind_speed'] == pytest.approx(expected / 10.0, rel=1e-5)
    sensor.deinit()
    device.close.assert_called_once()


def test_invalid_pin(gpio_backend):
    device, factory = gpio_backend
    with pytest.raises(SensorException, match='not valid'):
        wind_sensor.WindSpeedSensorWhSpWs01({}, 'Wind', None, None, pin_1_name='D99')
    factory.assert_not_called()


def test_initialization_failure(gpio_backend):
    device, factory = gpio_backend
    factory.side_effect = RuntimeError('GPIO unavailable')
    with pytest.raises(SensorException, match='GPIO unavailable'):
        wind_sensor.WindSpeedSensorWhSpWs01({}, 'Wind', None, None, pin_1_name='D25')


def test_callback_setup_failure_closes_device(gpio_backend):
    device, factory = gpio_backend

    class FailingDevice:
        close = Mock()

        @property
        def when_activated(self):
            return None

        @when_activated.setter
        def when_activated(self, callback):
            raise RuntimeError('Edge detection unavailable')

    failing_device = FailingDevice()
    factory.return_value = failing_device
    with pytest.raises(SensorException, match='Edge detection unavailable'):
        wind_sensor.WindSpeedSensorWhSpWs01({}, 'Wind', None, None, pin_1_name='D25')
    failing_device.close.assert_called_once()