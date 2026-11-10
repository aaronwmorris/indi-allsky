from multiprocessing import Array
from types import SimpleNamespace


from indi_allsky import sensor
from indi_allsky.sensor_health import SensorHealth


def test_driver_failed_at_boot_recovers_independently_and_zero_is_valid(monkeypatch):
    now = [100.]
    monkeypatch.setattr(sensor.time, 'monotonic', lambda: now[0])

    class Device:
        METADATA = {'count': 1}
        instances = []
        def __init__(self, cfg, label, night, astro, **kwargs):
            self.name = label
            self.reads = 0
            self.closed = False
            self.instances.append(self)
            if label == 'C' and len(self.instances) == 2:
                raise OSError('not on bus yet')

        def update(self):
            self.reads += 1
            if self.name == 'C' and self.forced_error:
                raise OSError('device unplugged')
            return {'data': (0 if self.name == 'C' else 21.5,)}
        forced_error = False

        def deinit(self):
            self.closed = True

    monkeypatch.setattr(sensor.indi_allsky_sensors, 'test_driver', Device, raising=False)
    cfg = {'TEMP_SENSOR': {'A_CLASSNAME': 'test_driver', 'A_LABEL': 'A', 'C_CLASSNAME': 'test_driver',
                           'C_LABEL': 'C', 'C_USER_VAR_SLOT': 'sensor_user_35'}}
    values = Array('f', 110)
    health = SensorHealth()
    worker = sensor.SensorWorker(1, cfg, None, None, None, values, [0], [0], health)
    worker.init_sensors()
    worker.update_sensors()
    assert values[10] == 21.5
    assert health.metadata(now[0])['sensor_valid_mask'] == 1
    now[0] += 10
    worker.update_sensors()
    assert len(Device.instances) == 2
    now[0] += 6
    worker.update_sensors()
    assert values[35] == 0 and health.metadata(now[0])['sensor_valid_mask'] == (1 | (1 << 25))
    assert health.last_good[2] > 0

    old_a, old_c = worker.sensors[0], worker.sensors[2]
    old_c.forced_error = True
    for _ in range(3):
        now[0] += 15
        worker.update_sensors()
        assert health.metadata(now[0])['sensor_valid_mask'] == 1
    assert old_c.closed and not old_a.closed and worker.sensors[2] is None
    now[0] += 16
    worker.update_sensors()
    assert worker.sensors[0] is old_a and old_a.reads == 7
    assert worker.sensors[2] is not old_c
    assert health.metadata(now[0])['sensor_valid_mask'] == 1 | (1 << 25)
    # If the sensor worker stops reporting, old numbers will expire in subsequent images.
    assert health.metadata(now[0] + 70)['sensor_valid_mask'] == 0


def test_cache_and_unreceived_channels_do_not_advance_their_timestamps(monkeypatch):
    clock = [100.]
    monkeypatch.setattr(sensor.time, 'time', lambda: clock[0] + 10000)
    values = Array('f', 110)
    worker = sensor.SensorWorker(1, {}, None, None, None, values, [0], [0])
    device = SimpleNamespace(slot=35, METADATA={'count': 2})
    sample = {'data': (0, 0), 'observed': (0, 100)}
    worker._write_sample(2, device, sample, 100)
    assert worker.sensor_health.metadata(100)['sensor_valid_mask'] == 1 << 26
    assert worker.sensor_health.last_good[2] == 10100
    clock[0] = 170
    worker._write_sample(2, device, sample, 170)
    assert worker.sensor_health.metadata(170)['sensor_valid_mask'] == 0
    assert worker.sensor_health.last_good[2] == 10100


def test_warmup_cache_expires_and_only_the_stalled_sensor_reopens(monkeypatch):
    now = [100.]
    monkeypatch.setattr(sensor.time, 'monotonic', lambda: now[0])

    class CachedSensor:
        METADATA = {'count': 1}
        def __init__(self, cfg, label, night, astro, **kwargs):
            self.name = label
            self.cached = {'data': (3,)}
        def update(self):
            return self.cached
        def deinit(self):
            pass

    monkeypatch.setattr(sensor.indi_allsky_sensors, 'cache_test', CachedSensor, raising=False)
    cfg = {'TEMP_SENSOR': {'A_CLASSNAME': 'cache_test'}}
    worker = sensor.SensorWorker(1, cfg, None, None, None, Array('f', 110), [0], [0])
    worker.init_sensors()
    worker.update_sensors()
    old = worker.sensors[0]
    for stamp in (140, 161, 177, 193):
        now[0] = stamp
        worker.update_sensors()
    assert worker.sensors[0] is None and worker.sensor_health.metadata(193)['sensor_valid_mask'] == 0
    now[0] = 209
    worker.update_sensors()
    assert worker.sensors[0] is not old and worker.sensor_health.metadata(209)['sensor_valid_mask'] == 1


def test_explicitly_disabled_daytime_sample_leaves_a_gap_without_reopen(monkeypatch):
    now = [100.]
    monkeypatch.setattr(sensor.time, 'monotonic', lambda: now[0])
    class DarkOnly:
        METADATA = {'count': 1}
        def __init__(self, *args, **kwargs):
            self.name = 'sky'
        def update(self):
            return {'data': (0,), 'sample_disabled': True}
        def deinit(self):
            raise AssertionError('daylight must not restart this sensor')
    monkeypatch.setattr(sensor.indi_allsky_sensors, 'dark_test', DarkOnly, raising=False)
    worker = sensor.SensorWorker(1, {'TEMP_SENSOR': {'A_CLASSNAME': 'dark_test'}}, None,
                                 None, None, Array('f',110), [0], [0])
    worker.init_sensors()
    worker.update_sensors()
    first = worker.sensors[0]
    now[0] += 300
    worker.update_sensors()
    assert worker.sensors[0] is first
    assert worker.sensor_health.metadata(now[0])['sensor_valid_mask'] == 0
