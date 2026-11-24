"""Historical observations retain their time, sensor identity and missing values."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from indi_allsky.night_report_data import ZoneInfo

import cv2
import numpy as np
import pytest

from indi_allsky import night_report_data as data

SLOTS = {'air_temperature': 'sensor_user_10', 'humidity': 'sensor_user_11',
         'sky_temperature': 'sensor_user_14', 'lux': 'sensor_user_35'}


def frame(stamp=None, values=None, number=1, path=None):
    return SimpleNamespace(id=number, createDate=stamp or datetime(2026, 11, 14, 20),
                           data=values or {}, getFilesystemPath=lambda: path)


def test_recorded_offsets_distinguish_repeated_wall_times():
    berlin = ZoneInfo('Europe/Berlin')
    wall = datetime(2026, 10, 25, 2, 30)
    early = data.frame_time(frame(wall, {'utc_offset': 7200}), berlin)
    late = data.frame_time(frame(wall, {'utc_offset': 3600}), berlin)
    assert late.timestamp()-early.timestamp() == 3600
    assert early.isoformat() == '2026-10-25T02:30:00+02:00'
    assert late.isoformat() == '2026-10-25T02:30:00+01:00'


def test_unrecorded_ambiguous_and_nonexistent_wall_times_are_not_invented():
    berlin = ZoneInfo('Europe/Berlin')
    assert data.frame_time(frame(datetime(2026, 10, 25, 2, 30)), berlin) is None
    assert data.frame_time(frame(datetime(2026, 3, 29, 2, 30)), berlin) is None
    ordinary = data.frame_time(frame(datetime(2026, 11, 14, 20)), berlin)
    assert ordinary.isoformat() == '2026-11-14T20:00:00+01:00'


def test_aware_capture_timestamp_overrides_conflicting_offset():
    stamp = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)
    assert data.frame_time(frame(stamp, {'utc_offset': 3600}), ZoneInfo('Europe/Berlin')) == stamp


def test_historical_temperature_unit_is_used_before_requested_display_unit():
    f = frame(values={'temp_display': 'f', 'sensor_user_10': 50, 'sensor_user_11': 100,
                      'sensor_user_14': -4, 'sensor_user_35': 0})
    sample = data.sample(f, datetime(2026, 11, 14, tzinfo=timezone.utc), SLOTS, '°C')
    assert sample['air_temperature'] == pytest.approx(10)
    assert sample['sky_temperature'] == pytest.approx(-20)
    assert sample['dew_point'] == pytest.approx(10)
    assert sample['lux'] == 0
    fahrenheit = data.sample(f, datetime(2026, 11, 14, tzinfo=timezone.utc), SLOTS, '°F')
    assert fahrenheit['air_temperature'] == pytest.approx(50)
    assert fahrenheit['dew_point'] == pytest.approx(50)


def test_dew_point_requires_valid_pair_not_stale_shared_slot():
    valid_air, valid_sky = 1, 1 << 4
    f = frame(values={'temp_display': 'c', 'sensor_user_10': 10, 'sensor_user_11': 50,
                      'sensor_user_14': -20, 'sensor_user_35': .001,
                      'sensor_user_2': 99, 'sensor_valid_mask': valid_air | valid_sky})
    sample = data.sample(f, datetime(2026, 11, 14, tzinfo=timezone.utc), SLOTS, '°C')
    assert sample['air_temperature'] == 10 and sample['sky_temperature'] == -20
    assert sample['lux'] is None and sample['dew_point'] is None
    f.data.pop('sensor_valid_mask')
    sample = data.sample(f, datetime(2026, 11, 14, tzinfo=timezone.utc), SLOTS, '°C')
    assert sample['dew_point'] == pytest.approx(0.1, abs=.2)
    f.data['sensor_user_11'] = 0
    assert data.sample(f, datetime.now(timezone.utc), SLOTS, '°C')['dew_point'] is None


def test_saved_sensor_identity_survives_later_slot_reconfiguration():
    old = dict(SLOTS, lux='sensor_user_20')
    f = frame(values={'night_report_context': {'sensors': old}, 'sensor_user_20': .001,
                      'sensor_user_35': 800, 'temp_display': 'c'})
    sample = data.sample(f, datetime.now(timezone.utc), SLOTS, '°C')
    assert sample['lux'] == .001


def test_environment_pair_comes_from_same_sensor(monkeypatch):
    monkeypatch.setattr(data, 'build_slot_label_map', lambda config: {
        0: {'key': 'camera_temp'}, 10: {'key': 'sensor_a_temperature'},
        11: {'key': 'sensor_a_relative_humidity'}, 14: {'key': 'sensor_b_temperature'},
        15: {'key': 'sensor_b_sky_temperature'}, 20: {'key': 'sensor_c_relative_humidity'},
        35: {'key': 'sensor_d_lux'},
    })
    assert data.sensor_slots({}) == dict(SLOTS, sky_temperature='sensor_user_15')


def test_geometry_and_capture_time_reused_without_rereading_images(monkeypatch):
    source = np.zeros((20, 3, 3), dtype=np.uint8)
    source[:, 0] = 255
    source[:, 1] = (40, 20, 10)
    source[:, 2] = (80, 60, 50)
    first, second = frame(number=1), frame(number=2)
    kg = SimpleNamespace(report_entries=[first, second], keogram_data=source,
                         crop_top=0, crop_bottom=0, trimEdges=lambda image: image,
                         timestamps=[100, 200])
    actual = [datetime(2026, 11, 14, 20, tzinfo=timezone.utc),
              datetime(2026, 11, 14, 21, tzinfo=timezone.utc)]
    def fail_read(*args):
        pytest.fail('Existing keogram must be reused without reading full exposures')
    monkeypatch.setattr(data.Image, 'open', fail_read)
    strips, stamps = data._strips({}, list(zip([first, second], actual)), keogram_source=kg)
    assert stamps == [value.timestamp() for value in actual]
    assert strips.shape == (320, 2, 3)
    assert tuple(strips[100, 0]) == (10, 20, 40)
    assert tuple(strips[100, 1]) == (50, 60, 80)


def test_backfill_uses_real_minute_samples_without_filling_capture_gap(tmp_path):
    config = {'KEOGRAM_ANGLE': 0, 'ORB_PROPERTIES': {'RADIUS': 0}}
    origin = datetime(2026, 11, 14, 20, tzinfo=timezone.utc)
    timed = []
    for i, seconds in enumerate([0, 30, 60, 600]):
        path = tmp_path/f'frame-{i}.png'
        image = np.full((30, 40, 3), (30, 20+i, 10), dtype=np.uint8)
        assert cv2.imwrite(str(path), image)
        dated = origin + timedelta(seconds=seconds)
        timed.append((frame(dated, number=i, path=path), dated))
    strips, stamps = data._strips(config, timed)
    assert strips.shape == (320, 3, 3)
    assert stamps == [origin.timestamp()+seconds for seconds in [0, 60, 600]]


def test_recorded_location_overrides_current_mobile_location():
    camera = SimpleNamespace(latitude=40, longitude=-3, elevation=500)
    first = frame(values={'night_report_context': {'location': [52.7, 12.4, 60]}})
    location, note = data._location(camera, [(first, None)])
    assert location == (52.7, 12.4, 60)
    other = frame(values={'night_report_context': {'location': [50, 10, 60]}})
    location, note = data._location(camera, [(first, None), (other, None)])
    assert location is None and 'changed' in note


def test_prepare_report_uses_same_night_for_all_six_astronomical_events(monkeypatch):
    berlin = ZoneInfo('Europe/Berlin')
    monkeypatch.setattr(data, 'camera_timezone', lambda camera: berlin)
    monkeypatch.setattr(data, 'sensor_slots', lambda config: SLOTS)
    monkeypatch.setattr(data, '_strips', lambda config, timed, source:
                        (np.zeros((320, len(timed), 3), dtype=np.uint8),
                         [dated.timestamp() for _, dated in timed]))
    camera = SimpleNamespace(name='Mobile Allsky', latitude=52.7, longitude=12.4, elevation=50)
    entries = [frame(datetime(2026, 11, 14, 17), {'utc_offset': 3600}, 1),
               frame(datetime(2026, 11, 15, 7), {'utc_offset': 3600}, 2)]
    report = data.prepare_report({'TEMP_DISPLAY': 'c'}, camera, date(2026, 11, 14), entries)
    assert report['timezone_name'] == 'Europe/Berlin'
    assert report['frame_times'][1]-report['frame_times'][0] == 14*3600
    kinds = [event['kind'] for event in report['events']]
    assert kinds.count('dusk') == kinds.count('dawn') == 2
    assert 'moonrise' in kinds and 'moonset' in kinds


@pytest.mark.parametrize('mask', [-1, 1.5, True, 'bad'])
def test_malformed_validity_masks_do_not_turn_missing_sensors_into_readings(mask):
    assert data.reading({'sensor_valid_mask': mask, 'sensor_user_10': 12}, 'sensor_user_10') is None


def test_missing_historical_temperature_unit_is_not_assumed_from_current_setting():
    f = frame(values={'sensor_user_10': 50, 'sensor_user_11': 80, 'sensor_user_14': -4,
                      'sensor_user_35': .001})
    result = data.sample(f, datetime.now(timezone.utc), SLOTS, '°C')
    assert result['air_temperature'] is None and result['sky_temperature'] is None
    assert result['dew_point'] is None and result['lux'] == .001


def test_metric_catalog_keeps_extra_sensors_and_omits_duplicate_primary_slots(monkeypatch):
    def probe(key, name, unit, kind=None):
        return dict(key=key, name=name, unit=unit, device_class=kind)
    monkeypatch.setattr(data, 'build_slot_label_map', lambda config: {
        0: probe('camera_temp', 'Camera', '°C', 'temperature'),
        10: probe('sensor_a_temperature', 'Air', '°C', 'temperature'),
        11: probe('sensor_a_relative_humidity', 'Humidity', '%'),
        12: probe('sensor_a_pressure', 'Pressure', 'hPa'),
        14: probe('sensor_b_temperature', 'Infrared sensor body', '°C', 'temperature'),
        15: probe('sensor_b_sky_temperature', 'Sky', '°C', 'temperature'),
        35: probe('sensor_d_lux', 'Light', 'lx'),
        36: probe('sensor_d_sqm', 'Uncalibrated SQM', 'mag/arcsec2'),
    })
    by_id = {metric['id']: metric for metric in data.metric_catalog({'TEMP_DISPLAY': 'c'})}
    assert set(by_id) == {'sky_temperature', 'lux', 'air_temperature', 'dew_point',
                          'sensor_user_11', 'sensor_user_12', 'sensor_user_14'}
    assert by_id['sensor_user_11']['unit'] == '%'
    assert by_id['sensor_user_12']['label'] == 'Pressure'
    assert by_id['sensor_user_14']['kind'] == 'temperature'


@pytest.mark.parametrize('saved,value,display,expected', [
    ('hPa', 1013.25, 'psi', 14.69595),
    ('inHg', 29.92126, 'hPa', 1013.25),
    ('mmHg', 760, 'hPa', 1013.25),
])
def test_extra_pressure_uses_historical_case_sensitive_configuration_values(saved, value, display, expected):
    metric = dict(id='sensor_user_12', label='Pressure', unit=display, kind='number')
    observation = frame(values={'pressure_display': saved, 'sensor_user_12': value})
    result = data.sample(observation, datetime.now(timezone.utc), SLOTS, '°C', [metric])
    assert result['sensor_user_12'] == pytest.approx(expected, rel=2e-5)


def test_extra_temperature_wind_and_humidity_are_converted_independently():
    metrics = [dict(id='sensor_user_14', label='Body', unit='°C', kind='temperature'),
               dict(id='sensor_user_20', label='Wind', unit='m/s', kind='number'),
               dict(id='sensor_user_11', label='Humidity', unit='%', kind='number')]
    observation = frame(values={'temp_display': 'f', 'windspeed_display': 'kph',
                                'sensor_user_14': 50, 'sensor_user_20': 36, 'sensor_user_11': 77})
    result = data.sample(observation, datetime.now(timezone.utc), SLOTS, '°C', metrics)
    assert result['sensor_user_14'] == 10
    assert result['sensor_user_20'] == 10
    assert result['sensor_user_11'] == 77


def test_prepare_uses_recorded_metric_catalog_and_excludes_unavailable_sensors(monkeypatch):
    berlin = ZoneInfo('Europe/Berlin')
    monkeypatch.setattr(data, 'camera_timezone', lambda camera: timezone.utc)
    monkeypatch.setattr(data, 'sensor_slots', lambda config: SLOTS)
    monkeypatch.setattr(data, 'metric_catalog', lambda config: [])
    monkeypatch.setattr(data, '_strips', lambda config, timed, source:
                        (np.zeros((320, len(timed), 3), dtype=np.uint8),
                         [dated.timestamp() for _, dated in timed]))
    metrics = [dict(id='lux', label='Historical light sensor', unit='lx', kind='lux'),
               dict(id='sensor_user_20', label='Historical body temperature', unit='°F', kind='temperature'),
               dict(id='sensor_user_21', label='Unavailable pressure', unit='hPa', kind='number')]
    context = dict(timezone='Europe/Berlin', sensors=SLOTS, metrics=metrics,
                   location=[52.7, 12.4, 50])
    observation = frame(datetime(2026, 11, 14, 20),
                        dict(night_report_context=context, utc_offset=3600, temp_display='f',
                             sensor_user_35=0, sensor_user_20=50, sensor_user_21=999,
                             pressure_display='hPa', sensor_valid_mask=(1 << 25) | (1 << 10)))
    observation.exposure = 30
    camera = SimpleNamespace(name='Moved camera', uuid='abc', id=2, latitude=40, longitude=-3, elevation=500)
    # A sensor plugged in partway through the night is still available.
    earlier = frame(datetime(2026, 11, 14, 19), {
        'night_report_context': dict(context, sensors={}, metrics=[]), 'utc_offset': 3600,
    }, number=0)
    report = data.prepare_report({'TEMP_DISPLAY': 'c'}, camera, date(2026, 11, 14), [earlier, observation])
    by_id = {metric['id']: metric for metric in report['metrics']}
    assert set(by_id) == {'lux', 'sensor_user_20'}
    assert by_id['sensor_user_20']['unit'] == '°C'
    assert by_id['sensor_user_20']['label'] == 'Historical body temperature'
    assert report['samples'][0]['sensor_user_20'] is None
    assert report['samples'][1]['sensor_user_20'] == 10
    assert report['samples'][1]['lux'] == 0
    assert report['timezone_name'] == 'Europe/Berlin'
    assert report['samples'][1]['camera_uuid'] == 'abc'
    assert report['samples'][1]['time_reference'] == 'recorded_capture_time'
    assert report['samples'][1]['exposure_seconds'] == 30


def test_reassigned_extra_sensor_slot_is_not_mislabeled_as_old_measurement():
    old = dict(id='sensor_user_20', label='Humidity outside', unit='%', kind='number')
    changed = dict(id='sensor_user_20', label='Battery charge', unit='%', kind='number')
    observation = frame(values={'night_report_context': {'metrics': [changed]}, 'sensor_user_20': 80})
    result = data.sample(observation, datetime.now(timezone.utc), SLOTS, '°C', [old])
    assert result['sensor_user_20'] is None


def test_recorded_temperature_unit_change_does_not_hide_same_extra_sensor():
    old = dict(id='sensor_user_20', label='Instrument body', unit='°F', kind='temperature')
    chosen = dict(old, unit='°C')
    observation = frame(values={'night_report_context': {'metrics': [old]}, 'temp_display': 'f',
                                'sensor_user_20': 50})
    result = data.sample(observation, datetime.now(timezone.utc), SLOTS, '°C', [chosen])
    assert result['sensor_user_20'] == 10
