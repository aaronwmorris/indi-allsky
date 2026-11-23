"""Scientific alignment and export behavior of the standalone night report."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from indi_allsky.night_report_render import (
    BACKGROUND, HEIGHT, PLOT, WIDTH, _keogram_pixels, _lux_scale,
    _samples, _segments, render_report,
)


def test_keogram_retains_elapsed_time_and_leaves_capture_outage_empty():
    # Irregular cadence must not turn a nine-minute outage into two columns.
    strips = np.zeros((2, 5, 3), dtype=np.uint8)
    strips[:] = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
    image, count = _keogram_pixels(strips, [0, 30, 60, 600, 630], 0, 630, 631, 8)
    assert count == 5
    assert tuple(image[3, 60]) == (0, 0, 255)
    assert tuple(image[3, 600]) == (255, 255, 0)
    assert tuple(image[3, 300]) == tuple(bytes.fromhex(PLOT[1:]))


def test_unsorted_and_duplicate_columns_keep_the_last_observation():
    source = np.array([[(10, 0, 0), (20, 0, 0), (30, 0, 0)]], dtype=np.uint8)
    result, count = _keogram_pixels(source, [60, 0, 60], 0, 60, 61, 1)
    assert count == 2
    assert tuple(result[0, 0]) == (20, 0, 0)
    assert tuple(result[0, -1]) == (30, 0, 0)


def test_sensor_failure_and_time_gap_both_break_lines():
    samples = _samples([
        {'timestamp': 0, 'lux': 0}, {'timestamp': 30, 'lux': .001},
        {'timestamp': 60, 'lux': None}, {'timestamp': 90, 'lux': .002},
        {'timestamp': 900, 'lux': .003}, {'timestamp': 930, 'lux': .004},
    ])
    assert list(_segments(samples, 'lux', 90)) == [
        [(0., 0.), (30., .001)], [(90., .002)], [(900., .003), (930., .004)],
    ]


def test_brightness_scale_keeps_true_zero_and_large_twilight_range():
    low, high, ticks, transform, note = _lux_scale([0., .0002, .001, 100.])
    assert transform(0) == 0
    assert transform(.0002) < transform(.001) < transform(100) <= high
    assert 0 in ticks and note
    assert low == 0


def test_csv_keeps_dst_offsets_missing_values_and_zero(tmp_path):
    first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc).timestamp()
    samples = [
        {'timestamp': first, 'utc_offset': 7200, 'sky_temperature': -30,
         'lux': 0, 'air_temperature': 2, 'dew_point': -1},
        {'timestamp': first+3600, 'utc_offset': 3600, 'sky_temperature': None,
         'lux': '=IMPORTXML("malicious")', 'air_temperature': False, 'dew_point': float('nan')},
    ]
    png, csv_path = tmp_path/'report.png', tmp_path/'report.csv'
    info = render_report(png, csv_path, title='Autumn night', samples=samples,
                         keogram_rgb=None, frame_times=[], events=[], timezone_name='Europe/Berlin')
    rows = list(csv.DictReader(csv_path.open()))
    assert rows[0]['timestamp_local'].endswith('02:30:00+02:00')
    assert rows[1]['timestamp_local'].endswith('02:30:00+01:00')
    assert rows[0]['sky_brightness_lux'] == '0'
    assert rows[1]['sky_brightness_lux'] == ''
    assert rows[1]['air_temperature_c'] == rows[1]['dew_point_c'] == ''
    assert info['samples'] == 2 and info['frames'] == 0
    with Image.open(png) as image:
        assert image.size == (WIDTH, HEIGHT)
        assert image.format == 'PNG'
        assert image.getpixel((0, 0)) == tuple(bytes.fromhex(BACKGROUND[1:]))


def test_csv_uses_recorded_offset_if_zone_name_is_unknown(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    csv_path = tmp_path/'report.csv'
    render_report(tmp_path/'report.png', csv_path, title='Mobile camera',
                  samples=[{'timestamp': stamp, 'utc_offset': 19800}],
                  keogram_rgb=None, frame_times=[], events=[], timezone_name='Unknown location',
                  temperature_unit='°F')
    row = next(csv.DictReader(csv_path.open()))
    assert row['timestamp_local'].endswith('05:30:00+05:30')
    assert row['utc_offset_seconds'] == '19800'
    assert 'air_temperature_f' in row


def test_twilight_and_moon_events_are_preserved_in_report_metadata(tmp_path):
    stamp = datetime(2026, 11, 14, 17, tzinfo=timezone.utc).timestamp()
    samples = [{'timestamp': stamp+i*60, 'lux': .001} for i in range(361)]
    events = [{'timestamp': stamp+i*3600, 'kind': kind, 'label': label}
              for i, kind, label in [(1, 'dusk', 'Astronomical dusk'),
                                     (2, 'moonset', 'Moonset'),
                                     (4, 'moonrise', 'Moonrise'),
                                     (5, 'dawn', 'Astronomical dawn')]]
    info = render_report(tmp_path/'report.png', tmp_path/'report.csv', title='Allsky 14 November',
                         samples=samples, keogram_rgb=np.full((30, 361, 3), 70, dtype=np.uint8),
                         frame_times=[sample['timestamp'] for sample in samples],
                         events=events, timezone_name='Europe/Berlin')
    assert [event['kind'] for event in info['events']] == ['dusk', 'moonset', 'moonrise', 'dawn']
    assert info['frames'] == 361


def test_empty_observations_and_mismatched_image_timestamps_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='timestamped observations'):
        render_report(tmp_path/'report.png', tmp_path/'report.csv', title='Empty', samples=[],
                      keogram_rgb=None, frame_times=[], events=[])
    with pytest.raises(ValueError, match='columns must match'):
        render_report(tmp_path/'report.png', tmp_path/'report.csv', title='Bad geometry',
                      samples=[{'timestamp': 123}], keogram_rgb=np.zeros((10, 2, 3), dtype=np.uint8),
                      frame_times=[123], events=[])


def test_selected_sensors_change_png_panels_but_csv_retains_all_available_metrics(tmp_path):
    metrics = [
        dict(id='sky_temperature', label='Sky temperature', unit='°C', kind='temperature'),
        dict(id='lux', label='Sky brightness', unit='lx', kind='lux'),
        dict(id='sensor_user_11', label='Relative humidity', unit='%', kind='number'),
        dict(id='sensor_user_12', label='Air pressure', unit='hPa', kind='number'),
    ]
    samples = [dict(timestamp=1794672000+i*60, utc_offset=3600, sky_temperature=-30,
                    lux=.001, sensor_user_11=55+i, sensor_user_12=1005+i/10) for i in range(5)]
    png, csv_path = tmp_path/'selected.png', tmp_path/'all.csv'
    info = render_report(png, csv_path, title='Selected weather sensors', samples=samples,
                         keogram_rgb=None, frame_times=[], events=[], metrics=metrics,
                         selected_metrics=['sensor_user_11', 'sensor_user_12', 'missing', 'sensor_user_11'])
    assert info['selected_metrics'] == ['sensor_user_11', 'sensor_user_12']
    assert info['height'] == 1340  # Two metric panels, irrespective of the four available sensors.
    rows = list(csv.DictReader(csv_path.open()))
    assert rows[0]['sensor_user_11_percent'] == '55'
    assert rows[0]['sensor_user_12_hpa'] == '1005'
    assert rows[0]['sky_brightness_lux'] == '0.001'
    assert rows[0]['sky_temperature_c'] == '-30'
    assert set(rows[0]['valid_fields'].split(';')) == {metric['id'] for metric in metrics}
    assert info['metrics'] == metrics and info['csv_schema_version'] == 1
    with Image.open(png) as image:
        assert image.size == (WIDTH, 1340)


def test_no_selection_is_keogram_only_while_default_uses_available_canonical_sensors(tmp_path):
    metrics = [dict(id='lux', label='Sky brightness', unit='lx', kind='lux'),
               dict(id='sensor_user_11', label='Humidity', unit='%', kind='number')]
    args = dict(title='Station', samples=[dict(timestamp=1794672000, lux=0, sensor_user_11=65)],
                keogram_rgb=None, frame_times=[], events=[], metrics=metrics)
    default = render_report(tmp_path/'default.png', tmp_path/'default.csv', **args)
    assert default['selected_metrics'] == ['lux'] and default['height'] == 1060
    none = render_report(tmp_path/'none.png', tmp_path/'none.csv', **args, selected_metrics=[])
    assert none['height'] == 780 and none['selected_metrics'] == []
    assert next(csv.DictReader((tmp_path/'none.csv').open()))['sensor_user_11_percent'] == '65'


def test_csv_schema_keeps_capture_identity_reception_time_and_distinct_same_time_rows(tmp_path):
    stamp = 1794672000.
    samples = [dict(timestamp=stamp, utc_offset=3600, camera_uuid='station-uuid', camera_id=1,
                    night_date='2026-11-14', image_id=image_id, exposure_seconds=30.,
                    time_reference='recorded_capture_time', gap_before_seconds=gap,
                    sensor_validity='tracked', lux=0.)
               for image_id, gap in [(12, None), (13, 0)]]
    csv_path = tmp_path/'export.csv'
    render_report(tmp_path/'export.png', csv_path, title='Export', samples=samples,
                  keogram_rgb=None, frame_times=[], events=[])
    rows = list(csv.DictReader(csv_path.open()))
    assert len(rows) == 2
    assert [row['image_id'] for row in rows] == ['12', '13']
    assert rows[0]['schema_version'] == '1'
    assert rows[0]['camera_uuid'] == 'station-uuid' and rows[0]['camera_id'] == '1'
    assert rows[0]['night_date'] == '2026-11-14'
    assert rows[0]['exposure_seconds'] == '30'
    assert rows[0]['time_reference'] == 'recorded_capture_time'
    assert rows[0]['sensor_validity'] == 'tracked'
    assert rows[0]['gap_before_seconds'] == '' and rows[1]['gap_before_seconds'] == '0'
    assert rows[0]['unix_time'] == '1794672000.000000'
    assert rows[0]['valid_fields'] == 'lux'


def test_metadata_cannot_inject_spreadsheet_formulas(tmp_path):
    csv_path = tmp_path/'export.csv'
    render_report(tmp_path/'export.png', csv_path, title='Imported camera',
                  samples=[dict(timestamp=1794672000, camera_uuid='=1+1',
                                time_reference='\t@danger', night_date='2026-11-14')],
                  keogram_rgb=None, frame_times=[], events=[])
    row = next(csv.DictReader(csv_path.open()))
    assert row['camera_uuid'].startswith("'")
    assert row['time_reference'].startswith("'")


def test_six_full_event_labels_have_room_in_header(tmp_path):
    stamp = 1794672000.
    labels = [('dusk', 'Astronomical dusk begins'), ('dusk', 'Astronomical night begins'),
              ('moonset', 'Moonset'), ('moonrise', 'Moonrise'),
              ('dawn', 'Astronomical night ends'), ('dawn', 'Astronomical dawn ends')]
    events = [dict(timestamp=stamp+(i+1)*3600, kind=kind, label=label)
              for i, (kind, label) in enumerate(labels)]
    info = render_report(tmp_path/'events.png', tmp_path/'events.csv', title='Full observing night',
                         samples=[dict(timestamp=stamp+i*60, lux=.001) for i in range(481)],
                         keogram_rgb=None, frame_times=[], events=events)
    assert len(info['events']) == 6
    from PIL import ImageDraw
    from indi_allsky.night_report_render import _font
    draw = ImageDraw.Draw(Image.new('RGB', (WIDTH, HEIGHT)))
    total = sum(draw.textlength(label+'  20:00', font=_font(23))+48 for _, label in labels)
    assert total <= WIDTH-148


def test_first_csv_row_defines_all_columns_without_external_manifest(tmp_path):
    import json
    metrics = [dict(id='lux', label='Sky brightness', unit='lx', kind='lux'),
               dict(id='sensor_user_11', label='Humidity "outside"', unit='%', kind='number')]
    csv_path = tmp_path/'export.csv'
    render_report(tmp_path/'report.png', csv_path, title='Station',
                  samples=[dict(timestamp=1794672000+i*30, lux=.001, sensor_user_11=50+i)
                           for i in range(2)],
                  keogram_rgb=None, frame_times=[], events=[], metrics=metrics, selected_metrics=['lux'])
    rows = list(csv.DictReader(csv_path.open()))
    definitions = json.loads(rows[0]['metric_catalog_json'])
    assert len(definitions) == 2
    assert definitions[1] == dict(metrics[1], csv_column='sensor_user_11_percent')
    assert rows[0][definitions[1]['csv_column']] == '50'
    assert all(metric['csv_column'] in rows[0] for metric in definitions)
    assert rows[1]['metric_catalog_json'] == ''
