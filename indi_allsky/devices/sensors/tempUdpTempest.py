from collections import deque
import json
import logging
import socket
import threading

from .tempApiTempest import _TempestSensorBase
from ..exceptions import SensorReadException


logger = logging.getLogger('indi_allsky')


class TempUdpTempest(_TempestSensorBase):
    """WeatherFlow Tempest local UDP broadcast sensor (port 50222)."""

    UDP_PORT = 50222
    RAIN_WINDOW_SECONDS = 3600

    METADATA = {
        **_TempestSensorBase.METADATA,
        'name' : 'Tempest Local UDP',
        'description' : 'WeatherFlow Tempest Local UDP Broadcast Sensor',
    }


    def __init__(self, *args, **kwargs):
        super(TempUdpTempest, self).__init__(*args, **kwargs)

        logger.warning('Initializing [%s] Tempest Local UDP Sensor', self.name)

        temp_sensor_conf = self.config.get('TEMP_SENSOR', {})
        serial = str(temp_sensor_conf.get('TEMPEST_DEVICE_SERIAL', '')).strip()
        self.device_serial = serial if serial else None

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._latest_obs = None
        self._last_obs_ts = None
        self._rain_samples = deque()

        self._sock = self._create_socket()
        self._thread = threading.Thread(
            target=self._listen_loop,
            name=f'TempUdpTempest-{self.name}',
            daemon=True,
        )
        self._thread.start()

        self.data = {
            'data' : tuple(),
        }


    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.settimeout(1.0)
        sock.bind(('', self.UDP_PORT))
        return sock


    def _listen_loop(self):
        while not self._stop_event.is_set():
            try:
                payload, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue

            try:
                msg = json.loads(payload.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

            self._handle_message(msg)


    def _handle_message(self, msg):
        if not isinstance(msg, dict):
            return

        if self.device_serial and msg.get('serial_number') != self.device_serial:
            return

        if msg.get('type') != 'obs_st':
            return

        obs_list = msg.get('obs')
        if not obs_list or not isinstance(obs_list[0], list) or len(obs_list[0]) < 13:
            return

        obs = obs_list[0]
        ts = float(obs[0] or 0.0)
        rain_mm = float(obs[12] or 0.0)

        with self._lock:
            if self._last_obs_ts is None or ts > self._last_obs_ts:
                self._rain_samples.append((ts, rain_mm))
                self._last_obs_ts = ts
            cutoff = ts - self.RAIN_WINDOW_SECONDS
            while self._rain_samples and self._rain_samples[0][0] < cutoff:
                self._rain_samples.popleft()
            self._latest_obs = obs


    def update(self):
        with self._lock:
            obs = list(self._latest_obs) if self._latest_obs is not None else None
            rain_1h = sum(sample[1] for sample in self._rain_samples)

        if obs is None:
            raise SensorReadException('No Tempest UDP obs_st observation received yet')

        wind_speed = float(obs[2] or 0.0)
        wind_gust = float(obs[3] or 0.0)
        wind_deg = float(obs[4] or 0.0)
        pressure_hpa = float(obs[6] or 0.0)
        temp_c = float(obs[7] or 0.0)
        rel_h = float(obs[8] or 0.0)
        illuminance = float(obs[9] or 0.0)
        uv = float(obs[10] or 0.0)
        solar_radiation = float(obs[11] or 0.0)

        logger.info(
            '[%s] Tempest UDP - temp: %0.1fc, humidity: %0.1f%%, pressure: %0.1fhPa',
            self.name,
            temp_c,
            rel_h,
            pressure_hpa,
        )

        self.data = self._build_data(
            temp_c=temp_c,
            rel_h=rel_h,
            pressure_hpa=pressure_hpa,
            wind_speed=wind_speed,
            wind_gust=wind_gust,
            wind_deg=wind_deg,
            rain_1h=rain_1h,
            solar_radiation=solar_radiation,
            uv=uv,
            illuminance=illuminance,
        )

        return self.data


    def deinit(self):
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
