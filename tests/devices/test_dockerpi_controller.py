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

if 'busio' not in sys.modules:
    mock_busio = MagicMock()
    sys.modules['busio'] = mock_busio

import pytest
from indi_allsky.devices.controllers.dockerpi import DockerPi4ChannelRelay


def test_dockerpi_4channel_relay():
    fake_i2c_bus = MagicMock()
    with patch('adafruit_bus_device.i2c_device.I2CDevice') as mock_i2c_dev_cls:
        mock_i2c = MagicMock()
        mock_i2c_dev = MagicMock()
        mock_i2c_dev.__enter__.return_value = mock_i2c
        mock_i2c_dev_cls.return_value = mock_i2c_dev

        relay = DockerPi4ChannelRelay(fake_i2c_bus, address=0x10)

        # Initially all 4 relays are initialized to OFF via I2C (4 write calls)
        assert mock_i2c.write.call_count == 4
        for r in (DockerPi4ChannelRelay.RELAY1, DockerPi4ChannelRelay.RELAY2,
                  DockerPi4ChannelRelay.RELAY3, DockerPi4ChannelRelay.RELAY4):
            assert relay.get_relay(r) == 0

        # Set relay on (assert write payload [RELAY1, 0xFF])
        mock_i2c.reset_mock()
        relay.set_relay(DockerPi4ChannelRelay.RELAY1, True)
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY1) == 1
        assert mock_i2c.write.call_count == 1
        assert mock_i2c.write.call_args[0][0] == bytearray([DockerPi4ChannelRelay.RELAY1, DockerPi4ChannelRelay.RELAY_ON])

        # Set relay off (assert write payload [RELAY1, 0x00])
        mock_i2c.reset_mock()
        relay.set_relay(DockerPi4ChannelRelay.RELAY1, False)
        assert relay.get_relay(DockerPi4ChannelRelay.RELAY1) == 0
        assert mock_i2c.write.call_count == 1
        assert mock_i2c.write.call_args[0][0] == bytearray([DockerPi4ChannelRelay.RELAY1, DockerPi4ChannelRelay.RELAY_OFF])

        # Invalid relay check
        with pytest.raises(ValueError):
            relay.set_relay(0x99, True)

        with pytest.raises(ValueError):
            relay.get_relay(0x99)
