import logging
import sqlite3
import time
from pathlib import Path
from threading import Lock

from .sensorBase import SensorBase
from ... import constants
from ..exceptions import SensorException, SensorReadException

logger = logging.getLogger('indi_allsky')


class RainSensorWhSpRg(SensorBase):

    MM_PER_TIP = 0.3
    HOUR_SECONDS = 3600
    DAY_SECONDS = 86400

    METADATA = {
        'name': 'MISOL WH-SP-RG Rain Gauge',
        'description': 'WH-SP-RG tipping bucket rain gauge (pulse output)',
        'count': 2,
        'labels': (
            'Rain Rate',
            'Rain 24h',
        ),
        'types': (
            constants.SENSOR_PRECIPITATION_RATE,
            constants.SENSOR_PRECIPITATION,
        ),
    }


    def __init__(self, *args, **kwargs):
        super(RainSensorWhSpRg, self).__init__(*args, **kwargs)

        pin_1_name = kwargs.get('pin_1_name')
        if not pin_1_name:
            raise SensorException('WH-SP-RG sensor pin not configured (TEMP_SENSOR.__*_PIN_1)')

        try:
            import board
            from gpiozero import Button
            from gpiozero.exc import GPIOZeroError
        except ImportError as e:
            raise SensorException('WH-SP-RG sensor requires board/gpiozero support: %s' % str(e)) from e

        if not hasattr(board, pin_1_name):
            raise SensorException('WH-SP-RG sensor pin name "%s" is not valid' % pin_1_name)

        self._pulse_lock = Lock()
        self._pending_tips = []
        self.input_device = None
        self._history = None

        try:
            pin_id = getattr(board, pin_1_name).id
            self.input_device = Button(pin_id, pull_up=True, bounce_time=0.02)
            state_dir = Path(self.config.get('VARLIB_FOLDER', '/var/lib/indi-allsky')).joinpath('rain-gauges')
            state_dir.mkdir(parents=True, exist_ok=True)
            self._history = sqlite3.connect(str(state_dir.joinpath('wh-sp-rg-{0:d}.sqlite3'.format(pin_id))))
            self._history.execute('CREATE TABLE IF NOT EXISTS tips (timestamp REAL NOT NULL)')
            self._history.execute('CREATE INDEX IF NOT EXISTS tips_timestamp ON tips (timestamp)')
            self._history.commit()
            self.input_device.when_pressed = self._count_tip
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, RuntimeError, GPIOZeroError) as e:
            if self.input_device is not None:
                self.input_device.close()
            if self._history is not None:
                self._history.close()
            raise SensorException('Unable to initialize WH-SP-RG sensor on pin %s: %s' % (pin_1_name, str(e))) from e

        logger.warning('[%s] Initialized WH-SP-RG rain gauge on pin %s (0.3 mm/tip)', self.name, pin_1_name)


    def _count_tip(self):
        with self._pulse_lock:
            self._pending_tips.append(time.time())


    def _read_history(self):
        # Only the sensor thread accesses SQLite; GPIO callbacks enqueue tips.
        with self._pulse_lock:
            now = time.time()
            pending = self._pending_tips
            self._pending_tips = []

        try:
            with self._history:
                self._history.executemany('INSERT INTO tips (timestamp) VALUES (?)', ((tip,) for tip in pending))
                self._history.execute('DELETE FROM tips WHERE timestamp <= ?', (now - self.DAY_SECONDS,))
                hour_tips, day_tips = self._history.execute(
                    'SELECT COALESCE(SUM(timestamp > ?), 0), COUNT(*) FROM tips WHERE timestamp <= ?',
                    (now - self.HOUR_SECONDS, now),
                ).fetchone()
        except sqlite3.Error as e:
            with self._pulse_lock:
                self._pending_tips = pending + self._pending_tips
            raise SensorReadException('WH-SP-RG rainfall history failure: %s' % str(e)) from e

        return hour_tips * self.MM_PER_TIP, day_tips * self.MM_PER_TIP


    def update(self):
        rain_rate, rain_24h = self._read_history()
        logger.info('[%s] WH-SP-RG rain: %0.1f mm/hr (last hour), %0.1f mm (last 24h)', self.name, rain_rate, rain_24h)
        return {
            'rain_rate': rain_rate,
            'rain_24h': rain_24h,
            'data': (
                rain_rate,
                rain_24h,
            ),
        }


    def deinit(self):
        if self.input_device is not None:
            self.input_device.close()
            self.input_device = None
        if self._history is not None:
            try:
                self._read_history()
            except SensorReadException:
                logger.exception('[%s] Unable to save WH-SP-RG rainfall history on shutdown', self.name)
            finally:
                self._history.close()
                self._history = None
