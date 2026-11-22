from types import SimpleNamespace

import pytest

from indi_allsky.devices.exceptions import SensorReadException
from indi_allsky.devices.sensors import tempUdpTempest


class _FakeSocket:
    def __init__(self):
        self.closed = False

    def recvfrom(self, bufsize):
        raise tempUdpTempest.socket.timeout()

    def close(self):
        self.closed = True


def _make_udp_sensor(monkeypatch, cfg=None):
    fake_sock = _FakeSocket()
    monkeypatch.setattr(tempUdpTempest.TempUdpTempest, '_create_socket', lambda self: fake_sock)
    sensor = tempUdpTempest.TempUdpTempest(cfg or {'TEMP_SENSOR': {}}, 'tempest-udp', [], [])
    return sensor, fake_sock


def _obs_st_packet(
    ts=1588948614,
    wind_avg=5.0,
    wind_gust=8.0,
    wind_dir=180,
    pressure=1013.25,
    temp_c=20.0,
    rh=50.0,
    lux=25000,
    uv=3.2,
    solar=350.0,
    rain_mm=0.5,
    serial='ST-00000512',
):
    return {
        'serial_number': serial,
        'type': 'obs_st',
        'hub_sn': 'HB-00013030',
        'obs': [
            [ts, 2.0, wind_avg, wind_gust, wind_dir, 6, pressure, temp_c, rh, lux, uv, solar, rain_mm, 0, 0, 0, 2.41, 1]
        ],
    }


def test_tempest_udp_raises_until_obs_received(monkeypatch):
    sensor, fake_sock = _make_udp_sensor(monkeypatch)
    try:
        with pytest.raises(SensorReadException, match='No Tempest UDP obs_st observation received yet'):
            sensor.update()
    finally:
        sensor.deinit()
    assert fake_sock.closed is True


def test_tempest_udp_parses_obs_st_and_converts_units(monkeypatch):
    sensor, _ = _make_udp_sensor(
        monkeypatch,
        {
            'TEMP_DISPLAY': 'f',
            'WINDSPEED_DISPLAY': 'mph',
            'PRESSURE_DISPLAY': 'inHg',
            'TEMP_SENSOR': {},
        },
    )
    try:
        sensor._handle_message(_obs_st_packet(rain_mm=1.25))
        result = sensor.update()

        assert result['wind_degrees'] == pytest.approx(180.0)
        assert result['data'][0] == pytest.approx(68.0)
        assert result['data'][1] == pytest.approx(68.0)
        assert result['data'][2] == pytest.approx(50.0)
        assert result['data'][3] == pytest.approx(1013.25 * 0.02952998057228486)
        assert result['data'][4] == pytest.approx(5.0 * 3.6 * 0.6213711922)
        assert result['data'][5] == pytest.approx(8.0 * 3.6 * 0.6213711922)
        assert result['data'][6] == pytest.approx(1.25 * 0.0393700787)
        assert result['data'][7] == pytest.approx(350.0)
        assert result['data'][8] == pytest.approx(3.2)
        assert result['data'][9] == pytest.approx(25000.0)
    finally:
        sensor.deinit()


def test_tempest_udp_rolling_rain_window_and_dedup(monkeypatch):
    sensor, _ = _make_udp_sensor(monkeypatch)
    try:
        sensor._handle_message(_obs_st_packet(ts=1000, rain_mm=1.0))
        sensor._handle_message(_obs_st_packet(ts=1000, rain_mm=1.0))  # duplicate timestamp ignored
        sensor._handle_message(_obs_st_packet(ts=2000, rain_mm=1.5))
        sensor._handle_message(_obs_st_packet(ts=5000, rain_mm=0.75))  # 1000 is outside 3600s window

        result = sensor.update()
        assert result['data'][6] == pytest.approx(2.25)
    finally:
        sensor.deinit()


def test_tempest_udp_filters_by_serial_and_ignores_other_types(monkeypatch):
    sensor, _ = _make_udp_sensor(
        monkeypatch,
        {'TEMP_SENSOR': {'TEMPEST_DEVICE_SERIAL': 'ST-TARGET'}},
    )
    try:
        sensor._handle_message({'serial_number': 'ST-TARGET', 'type': 'rapid_wind', 'ob': [100, 3.0, 90]})
        sensor._handle_message(_obs_st_packet(serial='ST-OTHER', temp_c=10.0))
        with pytest.raises(SensorReadException):
            sensor.update()

        sensor._handle_message(_obs_st_packet(serial='ST-TARGET', temp_c=24.5))
        result = sensor.update()
        assert result['data'][0] == pytest.approx(24.5)
    finally:
        sensor.deinit()
