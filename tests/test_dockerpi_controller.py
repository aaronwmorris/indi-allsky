import sys
from unittest.mock import MagicMock, patch

# Provide fallbacks for optional embedded hardware libraries if not present in test env
if 'micropython' not in sys.modules:
    mock_mp = MagicMock()
    mock_mp.const = lambda x: x
    sys.modules['micropython'] = mock_mp

if 'adafruit_bus_device' not in sys.modules:
    mock_abd = MagicMock()
    sys.modules['adafruit_bus_device'] = mock_abd
    sys.modules['adafruit_bus_device.i2c_device'] = mock_abd.i2c_device

import pytest
from indi_allsky.devices.controllers.dockerpi import DockerPi4ChannelRelay


def test_dockerpi_4channel_relay():
    fake_i2c_bus = MagicMock()
    with patch('adafruit_bus_device.i2c_device.I2CDevice') as mock_i2c_dev_cls:
        mock_i2c_dev = MagicMock()
        mock_i2c_dev.__enter__.return_value = MagicMock()
        mock_i2c_dev_cls.return_value = mock_i2c_dev

        relay = DockerPi4ChannelRelay(fake_i2c_bus, address=0x10)

        # Initially all relays are 0
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY1) == 0
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY2) == 0

        # Set relay on
        relay.set_relay(DockerPi4ChannelRelay.RELAY1, True)
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY1) == 1

        # Set relay off
        relay.set_relay(DockerPi4ChannelRelay.RELAY1, False)
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY1) == 0

        # Invalid relay check
        with pytest.raises(ValueError):
            relay.set_relay(0x99, True)

        with pytest.raises(ValueError):
            relay.get_relay(0x99)
