import pytest
import ast
import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from indi_allsky.charts import chart_definitions, chart_value, custom_charts, validate_custom_charts
from indi_allsky.charts import chart_configuration, validate_chart_configuration
from indi_allsky.charts import build_chart_data, render_saved_charts


ROOT = Path(__file__).resolve().parents[1]


def production_chart_handler(config, readings, args, camera=None, latest_image=None, detection_mask=None):
    from sqlalchemy import and_, column, func

    tree = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'JsonChartView')
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('getChartData', 'get_objects')]
    query = MagicMock()
    for name in ('add_columns', 'join', 'filter', 'order_by'):
        getattr(query, name).return_value = query
    query.__iter__.side_effect = lambda: iter(readings)
    query.first.return_value = latest_image
    query.camera_setup = MagicMock()
    image = SimpleNamespace(query=query, **{name: column(name) for name in (
        'createDate', 'sqm', 'stars', 'temp', 'gain', 'exposure', 'detections', 'data', 'camera')})
    namespace = {'request': SimpleNamespace(args=args), 'datetime': datetime, 'timedelta': timedelta,
                 'IndiAllSkyDbImageTable': image, 'IndiAllSkyDbCameraTable': SimpleNamespace(id=column('camera_id')),
                 'and_': and_, 'func': func, 'build_chart_data': build_chart_data, 'chart_definitions': chart_definitions,
                 'app': SimpleNamespace(logger=MagicMock())}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'production-chart-handler', 'exec'), namespace)
    handler = SimpleNamespace(indi_allsky_config=config, camera=camera or SimpleNamespace(local=True, data={'sensor_user_0': 'Sky temperature'}),
                              chart_history_seconds=900, camera_now=datetime(2026, 10, 4, 20, 45), cameraSetup=query.camera_setup,
                              _load_detection_mask=lambda binmode: detection_mask)
    handler.getChartData = lambda *values: namespace['getChartData'](handler, *values)
    return namespace['get_objects'](handler), query


def test_chart_opacity_defaults_to_thirty_percent_and_preserves_saved_values():
    assert chart_configuration({})['OVERLAY_OPACITY'] == 30
    assert validate_chart_configuration({})['OVERLAY_OPACITY'] == 30
    assert chart_configuration({'CHARTS': {'OVERLAY_OPACITY': 80}})['OVERLAY_OPACITY'] == 80


def test_legacy_chart_settings_and_remote_labels_are_preserved():
    config = {'CHARTS': {'CUSTOM_SLOT_1': 'sensor_user_25', 'CUSTOM_SLOT_1_MIN': -20}}
    definitions = chart_definitions(config, {'sensor_user_25': 'Sky temperature'})
    assert len(definitions) == 15
    assert definitions[6] == {'id': 'custom_1', 'source': 'sensor_user_25', 'label': 'Sky temperature', 'min': -20}


def test_custom_chart_count_is_not_fixed_to_ten():
    definitions = [{'id': 'custom_{0}'.format(index), 'source': 'sensor_user_{0}'.format(index), 'min': None}
                   for index in range(12)]
    assert len(custom_charts({'CHARTS': {'CUSTOM': definitions}})) == 12
    assert custom_charts({'CHARTS': {'CUSTOM': []}}) == []


def test_remote_chart_definitions_use_the_camera_configuration():
    metadata = {'chart_definitions': [{'id': 'sky', 'source': 'sensor_user_12', 'label': 'Sky'}]}
    assert custom_charts({'CHARTS': {'CUSTOM': []}}, metadata)[0]['id'] == 'sky'


def test_local_definitions_override_stale_published_metadata():
    config = {'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_12'}]}}
    metadata = {'chart_definitions': [], 'sensor_user_12': 'Sky temperature'}
    assert chart_definitions(config, metadata, is_local=True)[6]['label'] == 'Sky temperature'


def test_remote_visibility_is_mapped_by_source():
    config = {'CHARTS': {'CUSTOM': [{'id': 'local_sky', 'source': 'sensor_user_12'}],
                         'OVERLAY_IDS': ['local_sky'], 'VISIBLE_IDS': ['temp', 'local_sky'], 'SAVED_IMAGE_IDS': ['local_sky'],
                         'AXIS_LIMITS': {'local_sky': {'min': -50, 'max': 10}}}}
    metadata = {'chart_definitions': [{'id': 'remote_sky', 'source': 'sensor_user_12'}]}
    settings = chart_configuration(config, metadata, is_local=False)
    assert settings['OVERLAY_IDS'] == ['remote_sky']
    assert settings['SAVED_IMAGE_IDS'] == ['remote_sky']
    assert settings['VISIBLE_IDS'] == ['temp', 'remote_sky']
    assert settings['AXIS_LIMITS'] == {'remote_sky': {'min': -50.0, 'max': 10.0}}


@pytest.mark.parametrize('definition', [
    {'id': 'stars', 'source': 'sensor_user_10'},
    {'id': '../chart', 'source': 'sensor_user_10'},
    {'id': 'sky', 'source': 'unknown'},
    {'id': 'sky', 'source': 'sensor_user_10', 'min': float('nan')},
    {'id': 'sky', 'source': 'sensor_user_10', 'min': True},
])
def test_invalid_chart_definitions_are_rejected(definition):
    with pytest.raises(ValueError):
        validate_custom_charts([definition])


def test_duplicate_chart_identifiers_are_rejected():
    with pytest.raises(ValueError):
        validate_custom_charts([{'id': 'sky', 'source': 'sensor_user_10'}] * 2)


@pytest.mark.parametrize('value', [None, 'missing', float('nan'), float('inf'), True])
def test_missing_or_nonfinite_readings_are_gaps_not_zero(value):
    assert chart_value(value) is None


def test_valid_zero_and_negative_readings_are_preserved():
    assert chart_value(0) == 0
    assert chart_value(-27.3) == -27.3


@pytest.mark.parametrize('include_timestamp', [False, True])
def test_chart_timestamps_preserve_dates_values_gaps_and_legacy_format(include_timestamp):
    from datetime import datetime
    from types import SimpleNamespace

    dates = [datetime(2026, 10, 4, 23, 59, 10), datetime(2026, 10, 5, 0, 0, 5), datetime(2026, 10, 6, 0, 0, 5)]
    values = [20.4, None, 20.47]
    readings = [SimpleNamespace(createDate=date, temp=0, stars_rolling=0, jsqm=0, gain=0, exposure=0,
                                detections=0, data={'sensor_user_0': value}) for date, value in zip(dates, values)]
    points = build_chart_data(readings, [{'id': 'sky', 'source': 'sensor_user_0'}],
                              include_timestamp=include_timestamp)['sky']
    assert [point['y'] for point in points] == values
    assert [point['x'] for point in points] == ['23:59:10', '00:00:05', '00:00:05']
    if include_timestamp:
        assert points[1]['timestamp'] - points[0]['timestamp'] == 55
        assert points[2]['timestamp'] - points[1]['timestamp'] == 86400
    else:
        assert all(set(point) == {'x', 'y'} for point in points)


def test_legacy_aurora_sources_are_preserved():
    assert validate_custom_charts([{'id': 'aurora', 'source': 'kpindex'}])[0]['source'] == 'kpindex'


def test_default_preferences_preserve_existing_charts_and_disable_overlays():
    settings = chart_configuration({})
    assert len(settings['VISIBLE_IDS']) == 16
    assert settings['OVERLAY_IDS'] == []
    assert settings['SAVED_IMAGE_IDS'] == []


@pytest.mark.parametrize('key, destination', [('OVERLAY_IDS', 'Browser'), ('SAVED_IMAGE_IDS', 'Saved image')])
@pytest.mark.parametrize('count', [4, 5])
def test_image_chart_selection_limit_is_four(key, destination, count):
    selected = ['jsqm', 'stars', 'temp', 'exp', 'gain'][:count]
    config = {'CUSTOM': [], key: selected}
    if count == 5:
        with pytest.raises(ValueError, match='Only 4 charts are allowed for ' + destination):
            validate_chart_configuration(config)
    else:
        assert validate_chart_configuration(config)[key] == selected


def test_image_chart_limits_are_independent_and_history_is_unrestricted():
    selected = ['jsqm', 'stars', 'temp', 'exp', 'gain', 'detection']
    settings = validate_chart_configuration({'CUSTOM': [], 'VISIBLE_IDS': selected,
                                            'OVERLAY_IDS': selected[:4], 'SAVED_IMAGE_IDS': selected[-4:]})
    assert settings['VISIBLE_IDS'] == selected
    assert settings['OVERLAY_IDS'] == selected[:4]
    assert settings['SAVED_IMAGE_IDS'] == selected[-4:]


@pytest.mark.parametrize('key', ['OVERLAY_IDS', 'SAVED_IMAGE_IDS'])
@pytest.mark.parametrize('count', [4, 5])
def test_chart_save_enforces_image_chart_limits_without_overwriting_settings(key, count):
    application = create_chart_preview()
    configuration = application.extensions['chart_preview_config']
    previous = json.loads(json.dumps(configuration))
    settings = chart_configuration(configuration)
    settings[key] = ['jsqm', 'stars', 'temp', 'exp', 'gain'][:count]
    response = application.test_client().post('/ajax/charts', json={'CHARTS__CONFIG': json.dumps(settings)})
    assert response.status_code == (200 if count == 4 else 400)
    if count == 5:
        assert 'Only 4 charts are allowed' in response.json['CHARTS__CONFIG'][0]
        assert configuration == previous
        application.extensions['chart_preview_save'].assert_not_called()
    else:
        assert configuration['CHARTS'][key] == settings[key]


def test_saved_charts_disabled_leave_pixels_and_readings_untouched():
    import numpy

    image = numpy.full((480, 640, 3), 120, dtype=numpy.uint8)
    readings = MagicMock()
    assert render_saved_charts(image, {'CHARTS': {'OVERLAY_IDS': ['temp']}}, readings) is image
    readings.__iter__.assert_not_called()
    assert numpy.all(image == 120)


@pytest.mark.parametrize('selected', [['temp'], ['detection'], ['temp', 'detection'], ['jsqm', 'stars', 'temp', 'detection']])
def test_saved_charts_change_real_raster_pixels_only_in_the_selected_regions(selected):
    import numpy
    import cv2

    readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30) + timedelta(seconds=index),
                temp=-27 + index, stars_rolling=0, jsqm=None, exposure=15, gain=50,
                detections=index % 2, data={}) for index in range(8)]
    config = {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': selected}}
    image = numpy.full((1000, 1280, 3), 120, dtype=numpy.uint8)
    original = image.copy()
    result = render_saved_charts(image, config, readings, label_bounds=[(10, 10, 300, 190)])
    width = 585
    height = 336
    right = 16 + width * (1 if len(selected) == 1 else 2)
    first_end = 198 + height
    assert result is image
    assert numpy.array_equal(image[:198], original[:198])
    assert numpy.array_equal(image[:, :16], original[:, :16])
    assert numpy.array_equal(image[:, right:], original[:, right:])
    assert numpy.any(image[198:first_end, 16:right] != 120)
    assert numpy.any(image[198:first_end, 16:right, 0] > image[198:first_end, 16:right, 2])
    end = 198 + height * (1 if len(selected) <= 2 else 2)
    assert numpy.array_equal(image[end:], original[end:])
    success, encoded = cv2.imencode('.png', result)
    assert success
    assert numpy.array_equal(cv2.imdecode(encoded, cv2.IMREAD_COLOR), result)


@pytest.mark.parametrize('selected, image_width, base_width, expected', [
    (['temp'], 640, 260, (585, 336)),
    (['temp'], 960, 300, (675, 336)),
    (['temp'], 320, 260, (288, 336)),
    (['temp', 'gain'], 640, 260, (585, 336)),
    (['temp', 'gain', 'stars'], 1280, 260, (585, 336)),
    (['jsqm', 'stars', 'temp', 'exp'], 1280, 260, (585, 336)),
])
def test_saved_charts_keep_enlarged_dimensions_for_every_selection(monkeypatch, selected, image_width, base_width, expected):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    draw = FigureCanvasAgg.draw
    sizes = []
    def record_draw(canvas):
        sizes.append(canvas.get_width_height())
        draw(canvas)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    config = {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': selected, 'OVERLAY_WIDTH': base_width}}
    render_saved_charts(numpy.zeros((1600, image_width, 3), dtype=numpy.uint8), config, [])
    assert sizes == [expected] * len(selected)
    assert chart_configuration(config)['OVERLAY_WIDTH'] == base_width


def test_four_saved_charts_fill_two_rows_without_gaps_in_row_major_order(monkeypatch):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    colors = iter([10, 20, 30, 40])
    monkeypatch.setattr(FigureCanvasAgg, 'buffer_rgba',
                        lambda canvas: numpy.full((336, 585, 4), [next(colors), 0, 0, 255], dtype=numpy.uint8))
    image = numpy.full((1000, 1280, 3), 120, dtype=numpy.uint8)
    render_saved_charts(image, {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': ['jsqm', 'stars', 'temp', 'exp']}}, [])
    for index, color in enumerate([10, 20, 30, 40]):
        top = 120 + (index // 2) * 336
        left = 16 + (index % 2) * 585
        assert numpy.all(image[top:top + 336, left:left + 585, 2] == color)
    assert numpy.all(image[792:] == 120)
    assert numpy.all(image[:, 1186:] == 120)


@pytest.mark.parametrize('limits', [{}, {'min': 0, 'max': 100}])
def test_saved_humidity_chart_autoscales_despite_legacy_zero_minimum(monkeypatch, limits):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    drawn = []
    draw = FigureCanvasAgg.draw
    def record_draw(canvas):
        axes = canvas.figure.axes[0]
        drawn.append((axes.get_ylim(), axes.lines[0].get_ydata().tolist()))
        draw(canvas)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    config = {'CHARTS': {'CUSTOM': [{'id': 'humidity', 'source': 'sensor_user_0', 'min': 0}],
                        'SAVED_IMAGE_IDS': ['humidity'], 'AXIS_LIMITS': {'humidity': limits}}}
    values = [86.0, 86.1, 86.05]
    readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 23, 20) + timedelta(seconds=index * 30),
                temp=None, stars_rolling=None, jsqm=None, exposure=None, gain=None, detections=None,
                data={'sensor_user_0': value}) for index, value in enumerate(values)]
    render_saved_charts(numpy.zeros((480, 960, 3), dtype=numpy.uint8), config, readings)
    (lower, upper), plotted = drawn[0]
    assert plotted == values
    if limits:
        assert (lower, upper) == (0, 100)
    else:
        assert 85 < lower < 86
        assert 86.1 < upper < 87
        assert upper - lower < 1


def test_saved_charts_honor_axis_limits_and_preserve_gaps_and_negative_values(monkeypatch):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    draws = []
    draw = FigureCanvasAgg.draw
    def record_draw(canvas):
        axes = canvas.figure.axes[0]
        draws.append((axes.get_ylim(), axes.lines[0].get_ydata().copy()))
        draw(canvas)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    config = {'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_10', 'min': 0}],
                        'SAVED_IMAGE_IDS': ['sky'], 'AXIS_LIMITS': {'sky': {'min': -40, 'max': 10}}}}
    readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=None, stars_rolling=None,
                jsqm=None, exposure=None, gain=None, detections=None, data={'sensor_user_10': value})
                for value in (-27, None, 0)]
    render_saved_charts(numpy.zeros((480, 640, 3), dtype=numpy.uint8), config, readings)
    assert draws[0][0] == (-40, 10)
    assert draws[0][1][0] == -27
    assert numpy.isnan(draws[0][1][1])
    assert draws[0][1][2] == 0


@pytest.mark.parametrize('image_width', [320, 960])
@pytest.mark.parametrize('point_count', [1, 2, 5, 60])
def test_saved_chart_names_are_literal_and_timestamp_labels_stay_inside_panel(monkeypatch, image_width, point_count):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    draw = FigureCanvasAgg.draw
    text_bounds = []
    def record_draw(canvas):
        draw(canvas)
        renderer = canvas.get_renderer()
        axes = canvas.figure.axes[0]
        labels = axes.get_xticklabels()
        assert all(text.get_rotation() == 0 and text.get_fontsize() == 11 for text in labels)
        end = datetime(2026, 10, 4, 20, 30) + timedelta(minutes=point_count - 1)
        assert labels[0].get_text() == (end - timedelta(seconds=900)).strftime('%H:%M')
        assert labels[-1].get_text() == (datetime(2026, 10, 4, 20, 30) + timedelta(minutes=point_count - 1)).strftime('%H:%M')
        text_bounds.extend(text.get_window_extent(renderer) for text in labels)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    config = {'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_0', 'label': r'Sky $\bad$'}],
                        'SAVED_IMAGE_IDS': ['sky']}}
    readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30) + timedelta(minutes=index),
                temp=None, stars_rolling=None, jsqm=None, exposure=None, gain=None, detections=None,
                data={'sensor_user_0': -27}) for index in range(point_count)]
    render_saved_charts(numpy.zeros((480, image_width, 3), dtype=numpy.uint8), config, readings)
    width = min(585, image_width - 32)
    assert len(text_bounds) == (6 if image_width == 960 else 2)
    assert all(0 <= bounds.x0 < bounds.x1 <= width and 0 <= bounds.y0 < bounds.y1 <= 336 for bounds in text_bounds)
    assert all(first.x1 < second.x0 for first, second in zip(text_bounds, text_bounds[1:]))


def test_saved_charts_that_cannot_fit_do_not_overwrite_labels_or_resize_image():
    import numpy

    image = numpy.full((150, 240, 3), 120, dtype=numpy.uint8)
    result = render_saved_charts(image, {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': ['temp']}}, [],
                                label_bounds=[(0, 0, 240, 130)])
    assert result.shape == (150, 240, 3)
    assert numpy.all(result == 120)


@pytest.mark.parametrize('image_width, label, value', [
    (960, 'SHT31 (i2c) - SHT31D - Temperature', 20.49),
    (320, 'MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM', -123456),
    (960, 'Temperature', None),
    (960, 'Temperature', -27),
    (320, 'SHT31 (i2c) - SHT31D - Temperature', 20.43),
])
def test_saved_chart_text_is_large_and_fits_the_expanded_plot(monkeypatch, image_width, label, value):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    draw = FigureCanvasAgg.draw
    def record_draw(canvas):
        draw(canvas)
        renderer = canvas.get_renderer()
        value_text, title_text = canvas.figure.texts
        assert title_text.get_fontsize() == 14
        assert value_text.get_fontsize() == 16
        title_bounds = title_text.get_window_extent(renderer)
        value_bounds = value_text.get_window_extent(renderer)
        assert title_bounds.x1 <= value_bounds.x0 - 12
        axes = canvas.figure.axes[0]
        assert axes.bbox.width >= canvas.get_width_height()[0] * .65
        assert axes.get_position().height >= .45
        lower, upper = axes.get_ylim()
        assert axes.get_yticks() == pytest.approx([lower + (upper - lower) * index / 4 for index in range(5)])
        assert axes.get_yticks()[0] == pytest.approx(lower)
        assert axes.get_yticks()[-1] == pytest.approx(upper)
        top_label = axes.get_yticklabels()[-1]
        assert top_label.get_visible() and top_label.get_text()
        top_bounds = top_label.get_window_extent(renderer)
        assert top_bounds.y1 < min(title_bounds.y0, value_bounds.y0)
        if value is not None:
            assert upper > value
        y_labels = [text for tick, text in zip(axes.get_yticks(), axes.get_yticklabels()) if lower <= tick <= upper]
        texts = [title_text, value_text, *axes.get_xticklabels(), *y_labels,
                 axes.yaxis.get_offset_text(), *axes.texts]
        for text in texts:
            if not text.get_text() or not text.get_visible():
                continue
            bounds = text.get_window_extent(renderer)
            assert 0 <= bounds.x0 < bounds.x1 <= canvas.get_width_height()[0]
            assert 0 <= bounds.y0 < bounds.y1 <= 336
        assert all(text.get_fontsize() == 11 for text in axes.get_xticklabels() + axes.get_yticklabels())
        offset_bounds = axes.yaxis.get_offset_text().get_window_extent(renderer)
        if axes.yaxis.get_offset_text().get_text():
            assert not title_bounds.overlaps(offset_bounds)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    config = {'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_0', 'label': label}],
                        'SAVED_IMAGE_IDS': ['sky']}}
    readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30) + timedelta(seconds=index),
                temp=None, stars_rolling=None, jsqm=None, exposure=None, gain=None, detections=None,
                data={'sensor_user_0': value}) for index in range(2)]
    render_saved_charts(numpy.zeros((480, image_width, 3), dtype=numpy.uint8), config, readings)


@pytest.fixture
def saved_chart_worker():
    import cv2
    import numpy
    import tempfile
    import shutil
    from PIL import Image
    from sqlalchemy import create_engine, Table, MetaData, Column, DateTime, Float, Integer, JSON, func
    from sqlalchemy.orm import Session
    from indi_allsky import constants

    engine = create_engine('sqlite://')
    table = Table('images', MetaData(), Column('camera_id', Integer), Column('createDate', DateTime),
                  Column('sqm', Float), Column('stars', Integer), Column('temp', Float), Column('gain', Float),
                  Column('exposure', Float), Column('detections', Integer), Column('data', JSON))
    table.metadata.create_all(engine)
    session = Session(engine)
    image_table = SimpleNamespace(query=session.query(table), **{column.name: column for column in table.columns})
    renderer = MagicMock(wraps=render_saved_charts)
    namespace = {'IndiAllSkyDbImageTable': image_table, 'func': func, 'timedelta': timedelta,
                 'SimpleNamespace': SimpleNamespace, 'constants': constants, 'logger': MagicMock(),
                 'chart_configuration': chart_configuration, 'render_saved_charts': renderer,
                 'cv2': cv2, 'tempfile': tempfile, 'shutil': shutil, 'Path': Path, 'Image': Image}
    tree = ast.parse((ROOT / 'indi_allsky/image.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ImageWorker')
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef)
               and node.name in ('get_chart_metadata', 'apply_saved_charts', 'write_img')]
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'production-saved-chart-worker', 'exec'), namespace)
    ref = SimpleNamespace(exp_date=datetime(2026, 10, 4, 20, 30), camera_id=1, sqm_value=100,
                          stars=list(range(10)), lines=[], gain=50, exposure=15,
                          **{key: 0 for key in ('uptime', 'kpindex', 'ovation_max', 'aurora_mag_bt',
                            'aurora_mag_gsm_bz', 'aurora_plasma_density', 'aurora_plasma_speed',
                            'aurora_plasma_temp', 'aurora_n_hemi_gw', 'aurora_s_hemi_gw')})
    worker = SimpleNamespace(config={}, sensors_temp_av=[10.0] * 60, sensors_user_av=list(range(110)),
                             image_processor=SimpleNamespace(image=numpy.full((480, 640, 3), 120, dtype=numpy.uint8),
                                                             camera_sqm_raw_mag=21.3, chart_label_bounds=[]),
                             ref=ref, image_table=image_table, table=table, session=session, renderer=renderer,
                             logger=namespace['logger'])
    worker.get_chart_metadata = lambda ref: namespace['get_chart_metadata'](worker, ref)
    worker.apply_saved_charts = lambda: namespace['apply_saved_charts'](worker, ref, SimpleNamespace(data={}))
    worker.write_img = lambda: namespace['write_img'](worker, worker.image_processor.image, ref,
                                                    SimpleNamespace(data={}), jpeg_exif=b'')
    yield worker
    session.close()
    engine.dispose()


@pytest.mark.parametrize('configuration', [{}, {'CHARTS': {'OVERLAY_IDS': ['temp']}},
    {'CHARTS': {'SAVED_IMAGE_IDS': ['temp']}, 'FOCUS_MODE': True}])
def test_capture_skips_chart_queries_and_rendering_when_not_requested(saved_chart_worker, configuration):
    worker = saved_chart_worker
    worker.config = configuration
    worker.image_table.query = MagicMock()
    worker.apply_saved_charts()
    worker.image_table.query.with_entities.assert_not_called()
    worker.renderer.assert_not_called()


def test_capture_saved_charts_query_only_camera_history_and_include_current_frame(saved_chart_worker):
    import numpy

    worker = saved_chart_worker
    worker.config = {'TEMP_DISPLAY': 'f', 'CHARTS': {
        'CUSTOM': [{'id': 'sky', 'source': 'sensor_temp_0'}], 'SAVED_IMAGE_IDS': ['sky', 'stars']}}
    records = [{'camera_id': 1, 'createDate': worker.ref.exp_date - timedelta(minutes=6 - index),
                'sqm': 90, 'stars': index + 1, 'temp': -10, 'gain': 50, 'exposure': 15, 'detections': 0,
                'data': {'sensor_temp_0': 14.0}} for index in range(5)]
    records.extend([dict(records[0], camera_id=2),
                    dict(records[0], createDate=worker.ref.exp_date - timedelta(seconds=900)),
                    dict(records[0], createDate=worker.ref.exp_date),
                    dict(records[0], createDate=worker.ref.exp_date + timedelta(seconds=1))])
    worker.session.execute(worker.table.insert(), records)
    worker.apply_saved_charts()
    worker.renderer.assert_called_once()
    readings = worker.renderer.call_args.args[2]
    assert len(readings) == 6
    assert readings[0].stars_rolling == 1
    assert readings[4].stars_rolling == 3
    assert readings[-1].createDate == worker.ref.exp_date
    assert readings[-1].stars_rolling == pytest.approx(25 / 6)
    assert readings[-1].temp == 10
    assert readings[-1].data['sensor_temp_0'] == 50
    assert readings[-1].data['sensor_user_109'] == 109
    assert numpy.any(worker.image_processor.image != 120)
    worker.logger.exception.assert_not_called()


@pytest.mark.parametrize('history', [900, 3600])
def test_saved_chart_sparse_history_uses_selected_time_window(monkeypatch, history):
    import numpy
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    end = datetime(2026, 10, 4, 22, 56)
    readings = [SimpleNamespace(createDate=end - timedelta(seconds=age), temp=None, stars_rolling=None,
                jsqm=None, exposure=None, gain=None, detections=None, data={'sensor_user_0': value})
                for age, value in [(120, 20.4), (60, 20.6), (0, 20.47)]]
    draw = FigureCanvasAgg.draw
    plotted = []
    def record_draw(canvas):
        axes = canvas.figure.axes[0]
        plotted.append((axes.get_xlim(), axes.lines[0].get_xdata().tolist(), axes.lines[0].get_ydata().tolist()))
        draw(canvas)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    render_saved_charts(numpy.zeros((480, 960, 3), dtype=numpy.uint8), {'CHARTS': {
        'CUSTOM': [{'id': 'ambient', 'source': 'sensor_user_0', 'min': None}],
        'SAVED_IMAGE_IDS': ['ambient'], 'SAVED_IMAGE_HISTORY_SECONDS': history}}, readings)
    assert plotted == [((0, history), [history - 120, history - 60, history], [20.4, 20.6, 20.47])]


def test_capture_saved_sensor_chart_plots_distinct_historical_values(saved_chart_worker, monkeypatch):
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    worker = saved_chart_worker
    worker.config = {'CHARTS': {'CUSTOM': [{'id': 'ambient', 'source': 'sensor_user_0', 'min': None}],
                               'SAVED_IMAGE_IDS': ['ambient']}}
    worker.sensors_user_av[0] = 22.2
    records = [{'camera_id': 1, 'createDate': worker.ref.exp_date - timedelta(minutes=3 - index),
                'sqm': 90, 'stars': 10, 'temp': 40, 'gain': 50, 'exposure': 15, 'detections': 0,
                'data': {'sensor_user_0': value}} for index, value in enumerate([20.0, 21.0, 19.5])]
    worker.session.execute(worker.table.insert(), records)
    draw = FigureCanvasAgg.draw
    plotted = []
    def record_draw(canvas):
        plotted.append(canvas.figure.axes[0].lines[0].get_ydata().tolist())
        draw(canvas)
    monkeypatch.setattr(FigureCanvasAgg, 'draw', record_draw)
    worker.apply_saved_charts()
    assert plotted == [[20.0, 21.0, 19.5, 22.2]]
    worker.logger.exception.assert_not_called()


def test_capture_sensor_metadata_is_an_independent_per_frame_snapshot(saved_chart_worker):
    worker = saved_chart_worker
    worker.config = {}
    worker.sensors_user_av[0] = 20.4
    earlier = worker.get_chart_metadata(worker.ref)
    worker.sensors_user_av[0] = 20.47
    latest = worker.get_chart_metadata(worker.ref)
    assert earlier['sensor_user_0'] == 20.4
    assert latest['sensor_user_0'] == 20.47
    assert earlier is not latest


@pytest.mark.parametrize('history', [60, 900, 3600, 86400])
def test_capture_saved_history_selection_controls_database_window(saved_chart_worker, history):
    worker = saved_chart_worker
    worker.config = {'CHARTS': {'CUSTOM': [{'id': 'ambient', 'source': 'sensor_user_0'}],
                               'SAVED_IMAGE_IDS': ['ambient'], 'OVERLAY_HISTORY_SECONDS': 60,
                               'SAVED_IMAGE_HISTORY_SECONDS': history}}
    ages = [7200, 1800, 600, 30]
    records = [{'camera_id': 1, 'createDate': worker.ref.exp_date - timedelta(seconds=age),
                'sqm': 90, 'stars': 10, 'temp': 40, 'gain': 50, 'exposure': 15, 'detections': 0,
                'data': {'sensor_user_0': 20 + age / 3600}} for age in ages]
    worker.session.execute(worker.table.insert(), records)
    worker.apply_saved_charts()
    readings = worker.renderer.call_args.args[2]
    assert [reading.createDate for reading in readings] == [
        worker.ref.exp_date - timedelta(seconds=age) for age in ages if age < history] + [worker.ref.exp_date]
    assert [reading.data['sensor_user_0'] for reading in readings[:-1]] == [
        20 + age / 3600 for age in ages if age < history]
    worker.logger.exception.assert_not_called()


def test_capture_keeps_saving_when_optional_raster_renderer_is_unavailable(saved_chart_worker):
    import numpy

    worker = saved_chart_worker
    worker.config = {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': ['temp']}}
    worker.renderer.side_effect = ImportError('matplotlib is not installed')
    worker.apply_saved_charts()
    worker.logger.exception.assert_called_once()
    assert numpy.all(worker.image_processor.image == 120)


@pytest.mark.parametrize('file_type', ['png', 'jpg'])
def test_capture_writer_saves_identical_composited_latest_and_archive_images(saved_chart_worker, tmp_path, file_type):
    import cv2
    import numpy
    from indi_allsky import constants

    worker = saved_chart_worker
    worker.config = {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': ['temp']},
                     'IMAGE_FILE_TYPE': file_type, 'IMAGE_FILE_COMPRESSION': {'png': 3, 'jpg': 95}}
    worker.image_dir = tmp_path
    worker.filename_t = 'image_{0}_{1}.{2}'
    worker.ref.day_date = worker.ref.exp_date.date()
    worker.night_av = {constants.NIGHT_NIGHT: True}
    folder = tmp_path / 'exposures'
    folder.mkdir()
    worker._getImageFolder = lambda *args: folder
    worker.apply_saved_charts()
    latest, saved = worker.write_img()
    assert saved is not None
    assert latest.read_bytes() == saved.read_bytes()
    decoded = cv2.imread(str(saved))
    assert decoded.shape == worker.image_processor.image.shape
    assert numpy.mean(decoded[120:456, 16:601]) < 100
    if file_type == 'png':
        assert numpy.array_equal(decoded, worker.image_processor.image)


@pytest.mark.parametrize('display, expected', [('c', 10), ('f', 50), ('k', 283.15)])
def test_shared_chart_metadata_preserves_capture_sensor_values_and_units(saved_chart_worker, display, expected):
    worker = saved_chart_worker
    worker.config = {'TEMP_DISPLAY': display}
    metadata = worker.get_chart_metadata(worker.ref)
    for index in range(60):
        assert metadata['sensor_temp_{0}'.format(index)] == expected
        assert metadata['sensor_user_{0}'.format(index)] == index
    for index in range(100, 110):
        assert metadata['sensor_user_{0}'.format(index)] == index
    assert 'sensor_user_60' not in metadata
    assert metadata['camera_sqm_raw_mag'] == 21.3


@pytest.mark.parametrize('backend', ['opencv', 'pillow'])
@pytest.mark.parametrize('selected', [[], ['temp']])
def test_real_image_label_bounds_keep_saved_charts_below_text(backend, selected):
    import cv2
    import numpy
    from PIL import Image, ImageDraw, ImageFont
    from matplotlib import get_data_path

    tree = ast.parse((ROOT / 'indi_allsky/processing.py').read_text(encoding='utf-8'))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'drawText_' + backend)
    namespace = {'cv2': cv2, 'ImageFont': ImageFont}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'production-image-label-bounds', 'exec'), namespace)
    config = {'CHARTS': {'CUSTOM': [], 'SAVED_IMAGE_IDS': selected}, 'TEXT_PROPERTIES': {
        'FONT_FACE': 'FONT_HERSHEY_SIMPLEX', 'FONT_AA': 'LINE_AA', 'FONT_SCALE': .5,
        'FONT_THICKNESS': 1, 'FONT_OUTLINE': True}}
    processor = SimpleNamespace(config=config, chart_label_bounds=[])
    image = numpy.zeros((640, 640, 3), dtype=numpy.uint8)
    if backend == 'opencv':
        namespace[method.name](processor, image, 'Exposure 15s', (10, 160), (255, 255, 255))
    else:
        pillow_image = Image.fromarray(image)
        font = Path(get_data_path()) / 'fonts/ttf/DejaVuSans.ttf'
        namespace[method.name](processor, ImageDraw.Draw(pillow_image), 'Exposure 15s', font, 16,
                               (10, 160), (255, 255, 255))
        image = numpy.array(pillow_image)
    assert len(processor.chart_label_bounds) == 1
    bottom = processor.chart_label_bounds[0][3]
    assert bottom >= 160
    original = image.copy()
    render_saved_charts(image, config, [], label_bounds=processor.chart_label_bounds)
    assert numpy.array_equal(image[:bottom + 8], original[:bottom + 8])
    assert (not numpy.array_equal(image, original)) is bool(selected)


def test_capture_metadata_copies_label_bounds_for_browser_only_charts(saved_chart_worker):
    worker = saved_chart_worker
    worker.config = {'CHARTS': {'SAVED_IMAGE_IDS': []}}
    worker.image_processor.chart_label_bounds = [(10, 10, 300, 188)]
    metadata = worker.get_chart_metadata(worker.ref)
    assert metadata['chart_label_bounds'] == [[10, 10, 300, 188]]
    worker.image_processor.chart_label_bounds.clear()
    assert metadata['chart_label_bounds'] == [[10, 10, 300, 188]]


@pytest.mark.parametrize('bounds', [None, [[10, 10, 300, 188]]])
def test_latest_image_response_exposes_recorded_label_bounds_without_changing_legacy_payload(bounds):
    from sqlalchemy import and_, column

    tree = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'JsonLatestImageView')
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('getLatestImage', 'get_objects')]
    namespace = {'timedelta': timedelta, 'and_': and_, 'request': SimpleNamespace(args={'camera_id': '1'}),
                 'IndiAllSkyDbCameraTable': SimpleNamespace(id=column('id'))}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'production-latest-image-bounds', 'exec'), namespace)
    query = MagicMock()
    image = SimpleNamespace(width=640, height=480, data={'chart_label_bounds': bounds}, getUrl=lambda **kwargs: '/image.jpg')
    query.join.return_value.filter.return_value.order_by.return_value.first.return_value = image
    view = SimpleNamespace(camera_now=datetime(2026, 10, 4), web_nonlocal_images=False, s3_prefix=None,
                           model=SimpleNamespace(query=query, camera=object(), createDate=column('createDate')),
                           history_seconds=900, cameraSetup=MagicMock(), indi_allsky_config={}, capture_pause=False)
    view.getLatestImage = lambda camera_id, history: namespace['getLatestImage'](view, camera_id, history)
    result = namespace['get_objects'](view)['latest_image']
    expected = {'url': '/image.jpg', 'width': 640, 'height': 480, 'message': ''}
    if bounds:
        expected['label_bounds'] = bounds
    assert result == expected


def test_capture_composites_saved_charts_after_labels_and_before_final_image_write():
    tree = ast.parse((ROOT / 'indi_allsky/image.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ImageWorker')
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == 'processImage')
    calls = {node.func.attr: node.lineno for node in ast.walk(method)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ('label_image', 'apply_saved_charts', 'write_img', 'save_longterm_keogram_data')}
    assert calls['save_longterm_keogram_data'] < calls['label_image'] < calls['apply_saved_charts'] < calls['write_img']


def test_chart_and_image_visibility_are_independent():
    settings = validate_chart_configuration({'CUSTOM': [], 'VISIBLE_IDS': [], 'OVERLAY_IDS': ['stars', 'temp'],
                                            'SAVED_IMAGE_IDS': ['gain', 'temp']})
    assert settings['VISIBLE_IDS'] == []
    assert settings['OVERLAY_IDS'] == ['stars', 'temp']
    assert settings['SAVED_IMAGE_IDS'] == ['gain', 'temp']


def test_y_axis_defaults_preserve_suggested_legacy_scaling():
    settings = chart_configuration({})
    assert settings['AXIS_LIMITS'] == {}
    assert settings['CUSTOM'][0]['min'] == 0


def test_optional_axis_limits_apply_to_custom_and_standard_charts():
    settings = validate_chart_configuration({'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_0'}],
        'AXIS_LIMITS': {'sky': {'min': -50, 'max': 10}, 'stars': {'max': 100}, 'temp': {'min': None, 'max': None}}})
    assert settings['AXIS_LIMITS'] == {'sky': {'min': -50.0, 'max': 10.0}, 'stars': {'min': None, 'max': 100.0}}


@pytest.mark.parametrize('limits', [None, {'unknown': {}}, {'histogram': {}}, {'stars': []},
    {'stars': {'min': 10, 'max': 5}}, {'stars': {'min': 5, 'max': 5}}, {'stars': {'max': float('nan')}},
    {'stars': {'max': True}}, {'stars': {'min': 10 ** 1000}}])
def test_invalid_axis_limits_are_rejected(limits):
    with pytest.raises(ValueError):
        validate_chart_configuration({'AXIS_LIMITS': limits})


@pytest.mark.parametrize('settings', [
    {'OVERLAY_IDS': ['histogram']}, {'OVERLAY_IDS': ['stars', 'stars']},
    {'SAVED_IMAGE_IDS': ['histogram']}, {'SAVED_IMAGE_IDS': ['unknown']},
    {'VISIBLE_IDS': ['unknown']}, {'OVERLAY_WIDTH': 999}, {'OVERLAY_TOP': -1},
    {'OVERLAY_HISTORY_SECONDS': 86401}, {'OVERLAY_OPACITY': True},
    {'SAVED_IMAGE_HISTORY_SECONDS': 59}, {'SAVED_IMAGE_HISTORY_SECONDS': 86401},
    {'SAVED_IMAGE_HISTORY_SECONDS': True}, {'SAVED_IMAGE_HISTORY_SECONDS': '3600'},
])
def test_invalid_preferences_are_rejected(settings):
    with pytest.raises(ValueError):
        validate_chart_configuration(settings)


@pytest.mark.parametrize('saved_history', [None, 60, 3600, 86400])
def test_saved_history_is_independent_and_defaults_to_existing_browser_history(saved_history):
    settings = validate_chart_configuration({'OVERLAY_HISTORY_SECONDS': 1800,
                                             'SAVED_IMAGE_HISTORY_SECONDS': saved_history})
    assert settings['OVERLAY_HISTORY_SECONDS'] == 1800
    assert settings['SAVED_IMAGE_HISTORY_SECONDS'] == (1800 if saved_history is None else saved_history)
    assert validate_chart_configuration({'OVERLAY_HISTORY_SECONDS': 3600})['SAVED_IMAGE_HISTORY_SECONDS'] == 3600


def test_series_builder_supports_more_than_ten_charts_and_missing_values():
    custom = [{'id': 'custom_{0}'.format(index), 'source': 'sensor_user_{0}'.format(index)} for index in range(12)]
    definitions = chart_definitions({'CHARTS': {'CUSTOM': custom}})
    reading = SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=10.0, stars_rolling=None,
                              jsqm=100, exposure=15.0, gain=50, detections=1,
                              data={'sensor_user_0': -27.3, 'sensor_user_1': 0})
    result = build_chart_data([reading], definitions, 'f')
    assert len(result) == 18
    assert result['temp'][0]['y'] == 50
    assert result['stars'][0]['y'] is None
    assert result['custom_0'][0]['y'] == -27.3
    assert result['custom_1'][0]['y'] == 0
    assert result['custom_11'][0]['y'] is None
    assert list(build_chart_data([reading], definitions, selected_ids=['custom_11'])) == ['custom_11']


@pytest.mark.parametrize('histogram', ['0', '1'])
def test_production_endpoint_handles_dynamic_series_and_optional_histogram(histogram):
    custom = [{'id': 'custom_{0}'.format(index), 'source': 'sensor_user_{0}'.format(index)} for index in range(12)]
    reading = SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=10, stars_rolling=20,
                              jsqm=100, exposure=15, gain=50, detections=0, data={'sensor_user_0': -27.3})
    response, query = production_chart_handler({'CHARTS': {'CUSTOM': custom}}, [reading],
                                               {'camera_id': '1', 'histogram': histogram, 'series': 'custom_0,custom_11'})
    assert len(response['chart_definitions']) == 18
    assert response['chart_data']['custom_0'][0]['y'] == -27.3
    assert response['chart_data']['custom_11'][0]['y'] is None
    assert 'stars' not in response['chart_data']
    assert response['message'] == ''
    assert query.first.call_count == int(histogram)


def test_production_endpoint_preserves_legacy_series_and_empty_history():
    response, query = production_chart_handler({}, [], {'camera_id': '1', 'histogram': '0', 'limit_s': '-1'})
    assert set(response['chart_data']) == {'jsqm', 'jsqm_d', 'stars', 'temp', 'gain', 'exp', 'detection',
                                         'custom_1', 'custom_2', 'custom_3', 'custom_4', 'custom_5',
                                         'custom_6', 'custom_7', 'custom_8', 'custom_9', 'histogram'}
    assert response['chart_data']['jsqm_d'] == []
    assert response['message'] == 'No chart data in history range'
    query.first.assert_not_called()


@pytest.mark.parametrize('requested, expected', [(None, 900), ('5', 5), ('0', 0), ('-1', -1), ('100000', 86400)])
def test_production_endpoint_preserves_history_parameters_and_timestamp_jitter(requested, expected):
    timestamp = int(datetime(2026, 10, 4, 20, 30).timestamp())
    arguments = {'camera_id': '7', 'histogram': '0', 'timestamp': str(timestamp)}
    if requested is not None:
        arguments['limit_s'] = requested
    response, query = production_chart_handler({}, [], arguments)
    parameters = query.filter.call_args.args[0].compile().params
    assert parameters['camera_id_1'] == 7
    assert parameters['createDate_2'] == datetime.fromtimestamp(timestamp + 3)
    assert parameters['createDate_1'] == datetime.fromtimestamp(timestamp + 3) - timedelta(seconds=expected)
    assert response['message'] == 'No chart data in history range'
    query.camera_setup.assert_called_once_with(camera_id=7)


@pytest.mark.parametrize('display, expected', [('c', 10), ('f', 50), ('k', 283.15)])
def test_legacy_endpoint_builtin_values_units_and_camera_relative_default_time(display, expected):
    reading = SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=10, stars_rolling=20.9,
                              jsqm=100, exposure=15, gain=50, detections=2,
                              data={'sensor_user_10': 3, 'sensor_user_11': -2})
    response, query = production_chart_handler({'TEMP_DISPLAY': display}, [reading], {'camera_id': '3', 'histogram': '0'})
    values = {identifier: points[0]['y'] for identifier, points in response['chart_data'].items()
              if identifier not in ('histogram', 'jsqm_d')}
    assert values['temp'] == pytest.approx(expected)
    assert {identifier: values[identifier] for identifier in ('jsqm', 'stars', 'exp', 'gain', 'detection')} == {
        'jsqm': 100, 'stars': 20, 'exp': 15, 'gain': 50, 'detection': 1}
    assert values['custom_1'] == 3
    assert values['custom_2'] == -2
    assert response['chart_data']['stars'][0]['x'] == '20:30:00'
    assert query.filter.call_args.args[0].compile().params['createDate_2'] == datetime(2026, 10, 4, 20, 45, 3)
    query.camera_setup.assert_called_once_with(camera_id=3)


def test_production_endpoint_uses_selected_remote_camera_metadata():
    reading = SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=10, stars_rolling=20,
                              jsqm=100, exposure=15, gain=50, detections=0, data={'sensor_user_42': -17.5})
    camera = SimpleNamespace(local=False, data={'custom_chart_1_key': 'sensor_user_42',
                                               'custom_chart_1_min': -40, 'sensor_user_42': 'Remote sky'})
    response, query = production_chart_handler({}, [reading], {'camera_id': '9', 'histogram': '0'}, camera=camera)
    assert response['chart_data']['custom_1'][0]['y'] == -17.5
    assert response['chart_definitions'][6]['label'] == 'Remote sky'
    assert response['chart_definitions'][6]['min'] == -40
    query.camera_setup.assert_called_once_with(camera_id=9)
    assert query.filter.call_args.args[0].compile().params['camera_id_1'] == 9


@pytest.mark.parametrize('mode', ['L', 'RGB'])
@pytest.mark.parametrize('use_mask', [False, True])
def test_production_histogram_calculates_real_image_channels_and_roi(tmp_path, mode, use_mask):
    import numpy
    from PIL import Image

    path = tmp_path / 'histogram.png'
    Image.new(mode, (8, 8), 37 if mode == 'L' else (11, 22, 33)).save(path)
    latest = SimpleNamespace(binmode=2, getFilesystemPath=lambda: path)
    mask = numpy.zeros((8, 8), dtype=numpy.uint8) if use_mask else None
    if use_mask:
        mask[0:2, 0:3] = 255
    config = {'SQM_ROI': [0, 0, 8, 8]}
    reading = SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 30), temp=10, stars_rolling=20,
                              jsqm=100, exposure=15, gain=50, detections=0, data={})
    response, query = production_chart_handler(config, [reading], {'camera_id': '4', 'series': ''},
                                               latest_image=latest, detection_mask=mask)
    assert response['message'] == ''
    histogram = response['chart_data']['histogram']
    expected_count = 6 if use_mask else 16
    channels = {'gray': 37} if mode == 'L' else {'red': 11, 'green': 22, 'blue': 33}
    for channel, intensity in channels.items():
        assert len(histogram[channel]) == 256
        assert histogram[channel][intensity] == {'x': str(intensity), 'y': expected_count}
        assert sum(point['y'] for point in histogram[channel]) == expected_count
    for channel in set(histogram) - set(channels):
        assert histogram[channel] == []
    assert len(query.filter.call_args_list) == 2
    assert all(call.args[0].compile().params['camera_id_1'] == 4 for call in query.filter.call_args_list)


def test_overlay_request_skips_real_image_histogram_work(tmp_path):
    latest = SimpleNamespace(binmode=1, getFilesystemPath=MagicMock(return_value=tmp_path / 'absent.png'))
    response, query = production_chart_handler({}, [], {'camera_id': '1', 'histogram': '0'}, latest_image=latest)
    assert response['chart_data']['histogram'] == {'red': [], 'green': [], 'blue': [], 'gray': []}
    query.first.assert_not_called()
    latest.getFilesystemPath.assert_not_called()


def test_production_config_field_validates_and_persists_the_normalized_settings():
    from wtforms import Form, HiddenField
    from wtforms.validators import ValidationError

    tree = ast.parse((ROOT / 'indi_allsky/flask/forms.py').read_text(encoding='utf-8'))
    validator = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'CHARTS__CONFIG_validator')
    namespace = {'json': json, 'ValidationError': ValidationError, '__package__': 'indi_allsky.flask'}
    exec(compile(ast.Module(body=[validator], type_ignores=[]), 'production-chart-validator', 'exec'), namespace)
    form_type = type('ChartConfigForm', (Form,), {'CHARTS__CONFIG': HiddenField(validators=[namespace['CHARTS__CONFIG_validator']])})
    settings = chart_configuration({'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_0'}], 'OVERLAY_IDS': ['sky']}})
    form = form_type(data={'CHARTS__CONFIG': json.dumps(settings)})
    assert form.validate()
    assert not form_type(data={'CHARTS__CONFIG': '{broken'}).validate()
    assert not form_type(data={'CHARTS__CONFIG': json.dumps({'OVERLAY_IDS': ['histogram']})}).validate()
    views = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in views.body if isinstance(node, ast.ClassDef) and node.name == 'AjaxConfigView')
    save = next(node for node in ast.walk(owner) if isinstance(node, ast.If) and ast.unparse(node.test) == "request.json.get('CHARTS__CONFIG')")
    config = {'CHARTS': {'CUSTOM_SLOT_1': 'sensor_user_10'}}
    exec(compile(ast.Module(body=[save], type_ignores=[]), 'production-chart-save', 'exec'),
         {'self': SimpleNamespace(indi_allsky_config=config), 'request': SimpleNamespace(json={'CHARTS__CONFIG': form.CHARTS__CONFIG.data}),
          'json': json, 'validate_chart_configuration': validate_chart_configuration})
    assert config['CHARTS']['CUSTOM'] == settings['CUSTOM']
    assert config['CHARTS']['OVERLAY_IDS'] == ['sky']
    assert config['CHARTS']['CUSTOM_SLOT_1'] == 'sensor_user_10'


def test_capture_publishes_dynamic_definitions_for_remote_cameras():
    tree = ast.parse((ROOT / 'indi_allsky/capture.py').read_text(encoding='utf-8'))
    statement = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                     and ast.unparse(node.targets[0]) == "camera_metadata['data']['chart_definitions']")
    custom = [{'id': 'custom_{0}'.format(index), 'source': 'sensor_user_{0}'.format(index)} for index in range(12)]
    metadata = {'data': {}}
    exec(compile(ast.Module(body=[statement], type_ignores=[]), 'production-camera-metadata', 'exec'),
         {'self': SimpleNamespace(config={'CHARTS': {'CUSTOM': custom}}), 'camera_metadata': metadata, 'custom_charts': custom_charts})
    assert len(custom_charts({}, metadata['data'])) == 12


def production_config_validation(configuration):
    from indi_allsky.exceptions import ConfigSaveException

    tree = ast.parse((ROOT / 'indi_allsky/config.py').read_text(encoding='utf-8'))
    defaults = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == '_base_config' for target in node.targets))
    chart_defaults = next(value for key, value in zip(defaults.value.args[0].keys, defaults.value.args[0].values)
                          if isinstance(key, ast.Constant) and key.value == 'CHARTS')
    validator = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_validateConfig')
    namespace = {'app': SimpleNamespace(logger=MagicMock()), 'ConfigSaveException': ConfigSaveException}
    exec(compile(ast.Module(body=[validator], type_ignores=[]), 'production-config-validation', 'exec'), namespace)
    namespace['_validateConfig'](SimpleNamespace(config=configuration, base_config={'CHARTS': ast.literal_eval(chart_defaults)}))


@pytest.mark.parametrize('value', [None, []])
def test_persistence_accepts_legacy_and_empty_chart_selections(value):
    production_config_validation({'CHARTS': {'CUSTOM': value, 'VISIBLE_IDS': value}})


@pytest.mark.parametrize('key', ['CUSTOM', 'VISIBLE_IDS', 'SAVED_IMAGE_IDS'])
@pytest.mark.parametrize('value', ['invalid', {}, 1, True])
def test_persistence_rejects_incorrect_chart_collection_types(key, value):
    from indi_allsky.exceptions import ConfigSaveException

    with pytest.raises(ConfigSaveException):
        production_config_validation({'CHARTS': {key: value}})


def test_saved_image_selection_requires_a_list_in_persistence():
    from indi_allsky.exceptions import ConfigSaveException

    production_config_validation({'CHARTS': {'SAVED_IMAGE_IDS': []}})
    with pytest.raises(ConfigSaveException):
        production_config_validation({'CHARTS': {'SAVED_IMAGE_IDS': None}})


def production_chart_settings_view(application, configuration, save):
    from indi_allsky.exceptions import ConfigSaveException
    from flask import request, jsonify
    from flask.views import View
    from flask_login import LoginManager, UserMixin, current_user, login_required
    from flask_wtf import FlaskForm
    from wtforms import HiddenField, BooleanField
    from wtforms.validators import DataRequired, ValidationError

    login = LoginManager(application)

    class PreviewUser(UserMixin):
        def __init__(self, identifier):
            self.id = identifier
            self.username = identifier
            self.is_admin = identifier == 'admin'

    @login.user_loader
    def load_user(identifier):
        return PreviewUser(identifier) if identifier in ('admin', 'reader') else None

    class PreviewBaseView(View):
        def __init__(self, **kwargs):
            self.indi_allsky_config = configuration
            self._indi_allsky_config_obj = SimpleNamespace(save=save)
            self._miscDb = application.extensions['chart_preview_state']

    session = MagicMock()
    task_factory = MagicMock(side_effect=lambda **values: SimpleNamespace(**values))
    application.extensions['chart_preview_db_session'] = session
    application.extensions['chart_preview_tasks'] = task_factory
    application.extensions['chart_preview_state'] = SimpleNamespace(setState=MagicMock())
    forms = ast.parse((ROOT / 'indi_allsky/flask/forms.py').read_text(encoding='utf-8'))
    validator = next(node for node in forms.body if isinstance(node, ast.FunctionDef) and node.name == 'CHARTS__CONFIG_validator')
    form = next(node for node in forms.body if isinstance(node, ast.ClassDef) and node.name == 'IndiAllskyChartConfigForm')
    namespace = {'json': json, 'FlaskForm': FlaskForm, 'HiddenField': HiddenField, 'BooleanField': BooleanField, 'DataRequired': DataRequired,
                 'ValidationError': ValidationError, '__package__': 'indi_allsky.flask', 'app': application,
                 'request': request, 'jsonify': jsonify, 'current_user': current_user, 'login_required': login_required,
                 'BaseView': PreviewBaseView, 'validate_chart_configuration': validate_chart_configuration,
                 'ConfigSaveException': ConfigSaveException, 'db': SimpleNamespace(session=session),
                 'IndiAllSkyDbTaskQueueTable': task_factory, 'TaskQueueQueue': SimpleNamespace(MAIN='main'),
                 'TaskQueueState': SimpleNamespace(MANUAL='manual'), 'constants': SimpleNamespace(STATUS_RELOADING='reloading')}
    exec(compile(ast.Module(body=[validator, form], type_ignores=[]), 'production-chart-settings-form', 'exec'), namespace)
    views = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in views.body if isinstance(node, ast.ClassDef) and node.name == 'AjaxChartConfigView')
    exec(compile(ast.Module(body=[owner], type_ignores=[]), 'production-chart-settings-view', 'exec'), namespace)
    return namespace['IndiAllskyChartConfigForm'], namespace['AjaxChartConfigView']


def create_chart_preview(login_disabled=True, save_error=None, csrf_enabled=False):
    from flask import Blueprint, Flask, jsonify, render_template, render_template_string, request, send_file
    from jinja2 import ChoiceLoader, DictLoader
    from wtforms import Form, SelectField
    from indi_allsky.charts import BUILTIN_CHARTS, MAX_CUSTOM_CHARTS

    templates = ROOT / 'indi_allsky/flask/templates'
    static = ROOT / 'indi_allsky/flask/static'
    application = Flask('chart-preview', template_folder=str(templates), static_folder=None)
    application.config.update(SECRET_KEY='chart-preview-tests', LOGIN_DISABLED=login_disabled, WTF_CSRF_ENABLED=csrf_enabled)
    if csrf_enabled:
        from flask_wtf.csrf import CSRFProtect
        CSRFProtect(application)
    blueprint = Blueprint('indi_allsky', __name__, static_folder=str(static), static_url_path='/assets')
    base = '''<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{% block title %}Chart preview{% endblock %}</title><link rel="stylesheet" href="/assets/css/dist.css">
        <script src="/assets/js/jquery-3.7.1.min.js"></script>
        <style>body{padding:16px}main{max-width:1200px;margin:auto}nav{display:flex;gap:20px;margin-bottom:20px}</style>
        {% block head %}{% endblock %}</head><body><main><nav><a href="/settings">Settings</a><a href="/charts">Charts</a>
        <a href="/latest">Latest image</a><a href="/canvas">Latest canvas</a></nav>{% block content %}{% endblock %}</main></body></html>'''
    application.jinja_loader = ChoiceLoader([DictLoader({'base.html': base}), application.jinja_loader])
    custom = [{'id': 'custom_{0}'.format(index), 'source': 'sensor_user_{0}'.format(index),
               'label': 'Sky temperature' if index == 0 else 'Sensor {0}'.format(index), 'min': None} for index in range(12)]
    configuration = {'CHARTS': chart_configuration({'CHARTS': {'CUSTOM': custom, 'OVERLAY_IDS': ['custom_0', 'stars']}})}
    choices = {'Sensors': [('sensor_user_{0}'.format(index), 'Sensor {0}'.format(index)) for index in range(110)]}
    save = MagicMock(side_effect=save_error)
    if save_error is None:
        save.side_effect = lambda username, note: production_config_validation(configuration)
    application.extensions['chart_preview_config'] = configuration
    application.extensions['chart_preview_save'] = save
    EditorForm, save_view = production_chart_settings_view(application, configuration, save)
    blueprint.add_url_rule('/ajax/charts', view_func=save_view.as_view('ajax_chart_config_view'))

    class HistoryForm(Form):
        HISTORY_SELECT = SelectField('History', choices=[('900', '15 Minutes'), ('1800', '30 Minutes'), ('3600', '1 Hour'), ('86400', '24 Hours')], default='900')

    def context():
        settings = chart_configuration(configuration)
        definitions = chart_definitions(configuration)
        return {'website_title': 'Chart preview', 'page_title': 'Charts', 'camera_id': 1, 'timestamp': 0,
                'refreshInterval': 15000, 'night': 1, 'latest_image_view': 'indi_allsky.js_latest_image_view',
                'chart_settings': settings, 'chart_definitions': definitions,
                'chart_overlays': dict(settings, definitions=definitions), 'form_history': HistoryForm(),
                'form_config': EditorForm(data={'CHARTS__CONFIG': json.dumps(settings)}),
                'can_manage_charts': True, 'chart_source_choices': choices,
                'chart_builtin_definitions': BUILTIN_CHARTS, 'chart_maximum': MAX_CUSTOM_CHARTS}

    @blueprint.route('/settings', endpoint='config_view', methods=['GET', 'POST'])
    def settings_page():
        if request.method == 'POST':
            try:
                configuration['CHARTS'] = validate_chart_configuration(json.loads(request.json['CHARTS__CONFIG']))
            except (ValueError, TypeError, KeyError) as error:
                return jsonify(error=str(error)), 400
            return jsonify(saved=True)
        return render_template_string('''{% extends 'base.html' %}{% block head %}<link rel="stylesheet" href="/assets/css/charts.css">
            <script defer src="/assets/js/chart-editor.js"></script>{% endblock %}{% block content %}
            <form id="preview-config">{% include 'config/charts.html' %}<button class="tw:btn tw:btn-primary" type="submit">Save configuration</button>
            <span id="saved" role="status"></span></form><script>document.getElementById('preview-config').addEventListener('submit',async event=>{
                event.preventDefault(); const response=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({CHARTS__CONFIG:document.getElementById('CHARTS__CONFIG').value})});
                document.getElementById('saved').textContent=response.ok?'Saved':'Invalid settings';});</script>{% endblock %}''', **context())

    @blueprint.route('/charts', endpoint='chart_view')
    def charts_page():
        return render_template('charts.html', **context())

    @blueprint.route('/latest')
    def latest_page():
        return render_template('index_img.html', **context())

    @blueprint.route('/canvas')
    def canvas_page():
        return render_template('index_canvas.html', **context())

    def preview_readings():
        start = application.extensions.get('chart_preview_reading_start', datetime(2026, 10, 4, 20, 0))
        return [SimpleNamespace(createDate=start + timedelta(seconds=index * 25),
                    temp=12 + index / 50, stars_rolling=40 + index % 12, jsqm=100 + index % 7, gain=50,
                    exposure=15, detections=index % 6 == 0,
                    data={'sensor_user_{0}'.format(source): application.extensions.get('chart_preview_sensor_user_0_values', {}).get(index, -27 + index / 20) if source == 0 else source * 2 + index % 7 for source in range(11)})
                    for index in range(36)]

    @blueprint.route('/js/charts', endpoint='js_chart_view')
    def chart_response():
        readings = preview_readings()
        response, query = production_chart_handler(configuration, readings, dict(request.args))
        if request.args.get('histogram', '1') == '1':
            response['chart_data']['histogram']['gray'] = [{'x': str(index), 'y': 100 - abs(index - 70)} for index in range(100)]
        return jsonify(response)

    @blueprint.route('/js/latest', endpoint='js_latest_image_view')
    def latest_response():
        return jsonify(latest_image={'url': '/image.jpg', 'message': '2026-10-04 20:45 | Exposure 15s | Gain 50',
                                     'label_bounds': [[10, 10, 360, 128]]})

    @blueprint.route('/image.jpg')
    def image_response():
        if configuration['CHARTS']['SAVED_IMAGE_IDS']:
            import cv2
            from io import BytesIO

            image = cv2.imread(str(ROOT / 'content/20210421_043940.jpg'))
            image = render_saved_charts(image, configuration, preview_readings(), label_bounds=[(10, 10, 360, 128)])
            success, encoded = cv2.imencode('.jpg', image)
            assert success
            return send_file(BytesIO(encoded.tobytes()), mimetype='image/jpeg')
        return send_file(ROOT / 'content/20210421_043940.jpg')

    application.register_blueprint(blueprint)
    return application


def test_manage_charts_targets_settings_below_the_charts_without_a_configuration_tab():
    page = create_chart_preview().test_client().get('/charts').get_data(as_text=True)
    assert 'href="#chart-settings"' in page
    assert page.index('data-chart-grid') < page.index('id="chart-settings"')
    assert 'data-chart-editor' in page
    assert page.index('Save Configuration') < page.index('data-chart-editor')
    assert page.index('name="RELOAD_ON_SAVE"') < page.index('data-chart-editor')
    assert 'Save charts' not in page
    assert 'nav-charts-tab' not in (ROOT / 'indi_allsky/flask/templates/config.html').read_text(encoding='utf-8')


@pytest.mark.parametrize('saved_enabled', [False, True])
def test_editor_selects_reload_for_saved_chart_edits_and_preserves_opt_out(saved_enabled):
    from urllib.parse import urlsplit

    playwright = pytest.importorskip('playwright.sync_api')
    application = create_chart_preview(csrf_enabled=True)
    application.extensions['chart_preview_config']['CHARTS']['SAVED_IMAGE_IDS'] = ['custom_0'] if saved_enabled else []
    client = application.test_client()
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True)
        except playwright.Error:
            try:
                browser = driver.chromium.launch(channel='msedge', headless=True)
            except playwright.Error:
                pytest.skip('No Chromium or Edge available for chart editor browser checks')
        try:
            page = browser.new_page()
            def serve_preview(route):
                request = route.request
                url = urlsplit(request.url)
                response = client.open(url.path + ('?' + url.query if url.query else ''), method=request.method,
                                       data=request.post_data, headers=dict(request.headers))
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
            page.route('**/*', serve_preview)
            page.goto('http://chart.test/charts', wait_until='networkidle')
            reload = page.locator('#RELOAD_ON_SAVE')
            assert not reload.is_checked()
            row = page.locator('.chart-editor-row[data-chart-id=custom_0]')
            row.locator('input[type=text]').fill('Renamed saved chart')
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            source = row.locator('select')
            alternative = source.evaluate('(select) => [...select.options].find(option => option.value !== select.value).value')
            source.select_option(alternative)
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            row.locator('summary').click()
            row.locator('[data-axis-limit=min]').fill('-40')
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            row.locator('summary').click()
            row.get_by_role('button', name='Move chart down', exact=True).click()
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            for destination in ('Browser', 'History'):
                row.locator('label').filter(has_text=destination).locator('input').click()
                assert reload.is_checked() is saved_enabled
                reload.uncheck()
            preference = page.locator('[data-chart-preference=OVERLAY_WIDTH]')
            preference.fill('300')
            preference.press('Tab')
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            browser_history = page.locator('[data-chart-preference=OVERLAY_HISTORY_SECONDS]')
            saved_history = page.locator('[data-chart-preference=SAVED_IMAGE_HISTORY_SECONDS]')
            assert browser_history.input_value() == '900'
            saved_history.select_option('3600')
            assert browser_history.input_value() == '900'
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            opacity = page.locator('[data-chart-preference=OVERLAY_OPACITY]')
            opacity_value = page.locator('[data-chart-opacity-value]')
            assert opacity_value.inner_text() == '30%'
            opacity.focus()
            opacity.press('ArrowRight')
            assert opacity.input_value() == '31'
            assert opacity_value.inner_text() == '31%'
            assert opacity.get_attribute('title') == '31%'
            assert opacity.get_attribute('aria-valuetext') == '31%'
            assert reload.is_checked() is saved_enabled
            reload.uncheck()
            with page.expect_navigation(wait_until='networkidle'):
                page.get_by_role('button', name='Save Configuration', exact=True).click()
            application.extensions['chart_preview_tasks'].assert_not_called()
            assert application.extensions['chart_preview_config']['CHARTS']['OVERLAY_WIDTH'] == 300
            assert application.extensions['chart_preview_config']['CHARTS']['SAVED_IMAGE_HISTORY_SECONDS'] == 3600
            page.wait_for_function("document.querySelector('[data-chart-preference=SAVED_IMAGE_HISTORY_SECONDS]').value === '3600'")
            assert saved_history.input_value() == '3600'
            assert application.extensions['chart_preview_config']['CHARTS']['OVERLAY_OPACITY'] == 31
            assert opacity_value.inner_text() == '31%'
            assert not reload.is_checked()
            saved = page.locator('.chart-editor-row[data-chart-id=custom_0] label').filter(has_text='Saved image').locator('input')
            saved.click()
            assert reload.is_checked()
            if not saved_enabled:
                reload.uncheck()
                saved.click()
                assert reload.is_checked()
        finally:
            browser.close()


@pytest.mark.parametrize('viewport', [(1440, 1000), (390, 844)])
@pytest.mark.parametrize('fixed_limits', [False, True])
def test_history_page_autoscales_all_series_and_uses_capture_time_labels(viewport, fixed_limits):
    import re
    from urllib.parse import urlsplit

    playwright = pytest.importorskip('playwright.sync_api')
    application = create_chart_preview()
    config = application.extensions['chart_preview_config']
    definitions = custom_charts(config)
    next(definition for definition in definitions if definition['id'] == 'custom_0')['min'] = 0
    config['CHARTS']['CUSTOM'] = definitions
    config['CHARTS']['VISIBLE_IDS'] = ['jsqm', 'stars', 'temp', 'exp', 'gain', 'detection', 'custom_0', 'histogram']
    config['CHARTS']['AXIS_LIMITS'] = {'custom_0': {'min': 0, 'max': 100}} if fixed_limits else {}
    application.extensions['chart_preview_sensor_user_0_values'] = {index: 86.0 + (index % 3) * .05 for index in range(36)}
    client = application.test_client()
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True)
        except playwright.Error:
            try:
                browser = driver.chromium.launch(channel='msedge', headless=True)
            except playwright.Error:
                pytest.skip('No Chromium or Edge available for history chart browser checks')
        try:
            page = browser.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def serve_preview(route):
                url = urlsplit(route.request.url)
                response = client.get(url.path + ('?' + url.query if url.query else ''))
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
            page.route('**/*', serve_preview)
            page.goto('http://chart.test/charts', wait_until='networkidle')
            page.wait_for_function("Chart.getChart(document.querySelector('[data-chart-id=custom_0] canvas'))?.data.datasets[0].data.length === 36")
            charts = page.evaluate('''() => Object.fromEntries([...document.querySelectorAll('.chart-panel')].map(panel => {
                const chart = Chart.getChart(panel.querySelector('canvas'));
                if (chart.data.datasets[0].data.length > 1) {
                    const point = chart.getDatasetMeta(0).data[1];
                    chart.tooltip.setActiveElements([{datasetIndex:0,index:1}], {x:point.x,y:point.y});
                    chart.update('none');
                }
                return [panel.dataset.chartId, {min:chart.scales.y.min, max:chart.scales.y.max,
                    values:chart.data.datasets[0].data.map(point=>point.y), labels:chart.scales.x.ticks.map(tick=>tick.label),
                    tooltipTitle:chart.tooltip.title, timestamp:chart.data.datasets[0].data[1]?.x}];
            }))''')
            for identifier in ('jsqm', 'stars', 'temp', 'exp', 'gain', 'custom_0'):
                chart = charts[identifier]
                assert chart['labels'] and all(re.fullmatch(r'\d{2}:\d{2}', str(label)) for label in chart['labels'])
                assert chart['tooltipTitle'] == [chart['timestamp']]
                assert re.fullmatch(r'\d{2}:\d{2}:\d{2}', chart['tooltipTitle'][0])
                assert chart['min'] <= min(chart['values']) <= max(chart['values']) <= chart['max']
                if identifier == 'custom_0' and fixed_limits:
                    assert (chart['min'], chart['max']) == (0, 100)
                else:
                    assert chart['min'] > 0
            if not fixed_limits:
                assert charts['custom_0']['max'] - charts['custom_0']['min'] < 1
            assert charts['detection']['min'] == 0
            assert charts['detection']['max'] >= 1
            assert charts['histogram']['min'] == 0
            assert charts['histogram']['labels'] and all(re.fullmatch(r'\d+', str(label)) for label in charts['histogram']['labels'])
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('view', ['latest', 'canvas'])
@pytest.mark.parametrize('viewport', [(1440, 1000), (390, 844)])
@pytest.mark.parametrize('chart_count', [1, 2, 3, 4])
def test_browser_image_charts_show_larger_horizontal_minute_labels(view, viewport, chart_count):
    from urllib.parse import urlsplit
    from matplotlib.figure import Figure

    playwright = pytest.importorskip('playwright.sync_api')
    application = create_chart_preview()
    application.extensions['chart_preview_config']['CHARTS']['OVERLAY_IDS'] = ['custom_0', 'stars', 'temp', 'exp'][:chart_count]
    browser_history = 3600 if chart_count == 3 else 900
    application.extensions['chart_preview_config']['CHARTS']['OVERLAY_HISTORY_SECONDS'] = browser_history
    if chart_count == 3:
        from datetime import datetime
        application.extensions['chart_preview_reading_start'] = datetime(2026, 10, 4, 23, 50)
        definitions = custom_charts(application.extensions['chart_preview_config'])
        next(definition for definition in definitions if definition['id'] == 'custom_0')['min'] = 0
        application.extensions['chart_preview_config']['CHARTS']['CUSTOM'] = definitions
        application.extensions['chart_preview_sensor_user_0_values'] = {index: 86.0 + (index % 3) * .05 for index in range(36)}
    client = application.test_client()
    with playwright.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(headless=True)
        except playwright.Error:
            try:
                browser = driver.chromium.launch(channel='msedge', headless=True)
            except playwright.Error:
                pytest.skip('No Chromium or Edge available for chart overlay browser checks')
        try:
            page = browser.new_page(viewport={'width': viewport[0], 'height': viewport[1]})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def serve_preview(route):
                url = urlsplit(route.request.url)
                response = client.get(url.path + ('?' + url.query if url.query else ''))
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
            page.route('**/*', serve_preview)
            page.goto('http://chart.test/' + view, wait_until='networkidle')
            page.wait_for_function("Chart.getChart(document.querySelector('.latest-chart-overlays canvas'))?.data.datasets[0].data.length > 0")
            page.wait_for_function("getComputedStyle(document.querySelector('#latest-image-stage > img, #latest-image-stage > canvas')).opacity === '1'")
            charts = page.evaluate('''() => [...document.querySelectorAll('.latest-chart-overlays canvas')].map(canvas => {
                const chart = Chart.getChart(canvas);
                return {identifier:canvas.closest('.chart-panel').dataset.chartId, rotation: chart.scales.x.labelRotation, labels: chart.scales.x.ticks.map(tick => tick.label), font:chart.options.scales.x.ticks.font.size,
                    scale: parseFloat(canvas.closest('.latest-chart-overlays').style.getPropertyValue('--chart-overlay-scale')) || 1,
                        xMin:chart.scales.x.min, xMax:chart.scales.x.max, positions:chart.data.datasets[0].data.map(point=>point.x),
                    yTicks: chart.scales.y.ticks.map(tick => tick.value), yMin: chart.scales.y.min, yMax: chart.scales.y.max,
                        values: chart.data.datasets[0].data.map(point => point.y), suggestedMin: chart.options.scales.y.suggestedMin ?? null,
                    yFont: chart.options.scales.y.ticks.font.size, lineWidth: chart.data.datasets[0].borderWidth, radius: chart.data.datasets[0].pointRadius,
                        points: chart.data.datasets[0].data.length,
                        painted: [...canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data].some(value => value !== 0)};
            })''')
            assert len(charts) == chart_count
            for chart in charts:
                assert chart['rotation'] == 0
                assert chart['scale'] > 0
                assert chart['font'] == chart['yFont'] == pytest.approx(11 * 100 / 72 * chart['scale'])
                assert 2 <= len(chart['labels']) <= 7
                assert chart['yTicks'] == pytest.approx([chart['yMin'] + (chart['yMax'] - chart['yMin']) * index / 4 for index in range(5)])
                reference = Figure()
                axes = reference.add_subplot()
                axes.plot(chart['values'])
                lower, upper = axes.get_ylim()
                if chart['suggestedMin'] is not None:
                    lower = min(lower, chart['suggestedMin'])
                assert [chart['yMin'], chart['yMax']] == pytest.approx([lower, upper])
                if chart_count == 3 and chart['identifier'] == 'custom_0':
                    assert chart['suggestedMin'] is None
                    assert 85 < chart['yMin'] < 86
                    assert 86.1 < chart['yMax'] < 87
                    assert chart['yMax'] - chart['yMin'] < 1
                reference.clear()
                assert chart['yFont'] == pytest.approx(11 * 100 / 72 * chart['scale'])
                assert chart['lineWidth'] == pytest.approx(1.8 * 100 / 72 * chart['scale'])
                assert chart['radius'] == pytest.approx(2.7 * 100 / 72 / 2 * chart['scale'])
                assert len(set(chart['labels'])) == len(chart['labels'])
                assert chart['xMin'] == 0
                assert chart['xMax'] == browser_history
                assert chart['positions'][0] == browser_history - 875
                assert chart['positions'][-1] == browser_history
                assert chart['labels'][0] == ('23:04' if browser_history == 3600 else '19:59')
                assert chart['labels'][-1] == ('00:04' if browser_history == 3600 else '20:14')
                assert chart['points'] == 36
                assert chart['painted']
            assert not page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth')
            root = page.locator('.latest-chart-overlays')
            assert root.locator('[data-chart-status]').inner_text() == ''
            assert not root.locator('[data-chart-status]').is_visible()
            original_settings = json.loads(json.dumps(application.extensions['chart_preview_config']['CHARTS']))
            positions = root.locator('.chart-panel').evaluate_all('panels => panels.map(panel => {const rect=panel.getBoundingClientRect(); return {x:rect.x,y:rect.y,width:rect.width,height:rect.height};})')
            scale = charts[0]['scale']
            if view == 'latest':
                displayed_scale = page.locator('#latest-image').evaluate('media => Math.min(media.getBoundingClientRect().width / media.naturalWidth, media.getBoundingClientRect().height / media.naturalHeight)')
                assert scale == pytest.approx(displayed_scale)
            assert all(panel['width'] == pytest.approx(585 * scale, abs=.02) and panel['height'] == pytest.approx(336 * scale, abs=.02) for panel in positions)
            if chart_count > 1:
                assert positions[1]['x'] == pytest.approx(positions[0]['x'] + 585 * scale, abs=.02)
                assert positions[1]['y'] == positions[0]['y']
            if chart_count > 2:
                assert positions[2]['x'] == positions[0]['x']
                assert positions[2]['y'] == positions[0]['y'] + positions[0]['height']
            if chart_count > 3:
                assert positions[3]['x'] == positions[1]['x']
                assert positions[3]['y'] == positions[2]['y']
            chart_ids = root.locator('canvas').evaluate_all('canvases => canvases.map(canvas => Chart.getChart(canvas).id)')
            close = root.locator('.chart-overlay-close')
            assert close.count() == 1
            assert root.locator('.chart-panel .chart-overlay-close').count() == 0
            assert close.get_attribute('aria-label') == 'Dismiss browser chart block'
            assert close.get_attribute('title') == 'Dismiss charts'
            button_bounds = close.bounding_box()
            root_bounds = root.bounding_box()
            assert root_bounds['x'] <= button_bounds['x'] and button_bounds['x'] + button_bounds['width'] <= root_bounds['x'] + root_bounds['width']
            assert 0 <= button_bounds['y'] - root_bounds['y'] <= 8
            assert root.evaluate('''root => {
                const button = root.querySelector('.chart-overlay-close').getBoundingClientRect();
                return [...root.querySelectorAll('.chart-panel-header h2, .chart-value')].every(element => {
                    const text = element.getBoundingClientRect();
                    return text.right <= button.left || text.left >= button.right || text.bottom <= button.top || text.top >= button.bottom;
                });
            }''')
            if view == 'latest':
                close.click()
            else:
                close.press('Enter')
            assert not root.is_visible()
            assert root.locator('.chart-panel').count() == 0
            assert page.evaluate('(identifiers) => identifiers.every(identifier => !Chart.instances[identifier])', chart_ids)
            assert not root.evaluate("root => root.classList.contains('is-dragging')")
            assert page.evaluate("localStorage.getItem('chart-overlay-position:1')") is None
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            assert not root.is_visible()
            assert root.locator('.chart-panel').count() == 0
            assert application.extensions['chart_preview_config']['CHARTS'] == original_settings
            page.reload(wait_until='networkidle')
            page.wait_for_function("Chart.getChart(document.querySelector('.latest-chart-overlays canvas'))?.data.datasets[0].data.length > 0")
            assert root.locator('.chart-panel').count() == chart_count
            assert root.locator('.chart-overlay-close').count() == 1
            page.goto('http://chart.test/charts', wait_until='networkidle')
            assert page.locator('.chart-overlay-close').count() == 0
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('authenticated, admin, disabled, expected', [
    (False, False, False, False), (True, False, False, False),
    (True, True, False, True), (False, False, True, True)])
def test_production_chart_page_exposes_editor_only_to_configuration_administrators(authenticated, admin, disabled, expected):
    import math
    from flask import request
    from indi_allsky.charts import BUILTIN_CHARTS, MAX_CUSTOM_CHARTS

    application = create_chart_preview(login_disabled=disabled)
    save_view = application.view_functions['indi_allsky.ajax_chart_config_view'].view_class
    form_type = save_view.dispatch_request.__globals__['IndiAllskyChartConfigForm']
    template_view = type('PreviewTemplateView', (), {'get_context': lambda self: {'camera_id': 9}})
    choices = {'Sensors': [('sensor_user_0', 'User slot 0')]}
    namespace = {'TemplateView': template_view, 'request': request, 'math': math, 'json': json, 'app': application,
                 'current_user': SimpleNamespace(is_authenticated=authenticated, is_admin=admin),
                 'chart_configuration': chart_configuration, 'chart_definitions': chart_definitions,
                 'BUILTIN_CHARTS': BUILTIN_CHARTS, 'MAX_CUSTOM_CHARTS': MAX_CUSTOM_CHARTS,
                 'IndiAllskyChartHistoryForm': lambda: None, 'IndiAllskyChartConfigForm': form_type,
                 'IndiAllskyConfigForm': SimpleNamespace(CUSTOM_CHART_choices={}, SENSOR_SLOT_choices=choices)}
    tree = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ChartView')
    exec(compile(ast.Module(body=[owner], type_ignores=[]), 'production-chart-page-context', 'exec'), namespace)
    view = namespace['ChartView']()
    view.indi_allsky_config = application.extensions['chart_preview_config']
    view.camera = SimpleNamespace(local=True, data={'sensor_user_0': 'Sky temperature'})
    with application.test_request_context('/charts?timestamp=123'):
        context = view.get_context()
        assert context['can_manage_charts'] is expected
        assert context['timestamp'] == 123
        assert ('form_config' in context) is expected
        if expected:
            assert context['chart_source_choices']['Sensors'] == [('sensor_user_0', 'Sky temperature')]
            assert json.loads(context['form_config'].CHARTS__CONFIG.data)['CUSTOM'] == view.indi_allsky_config['CHARTS']['CUSTOM']
    assert choices == {'Sensors': [('sensor_user_0', 'User slot 0')]}


@pytest.mark.parametrize('user, expected', [(None, 401), ('reader', 400), ('admin', 200)])
def test_chart_only_save_preserves_configuration_and_requires_admin(user, expected):
    application = create_chart_preview(login_disabled=False)
    configuration = application.extensions['chart_preview_config']
    configuration['CCD_EXPOSURE_MAX'] = 42
    configuration['CHARTS']['CUSTOM_SLOT_1'] = 'sensor_user_10'
    previous = json.loads(json.dumps(configuration))
    client = application.test_client()
    if user:
        with client.session_transaction() as session:
            session['_user_id'] = user
            session['_fresh'] = True
    settings = chart_configuration({'CHARTS': {'CUSTOM': [], 'OVERLAY_IDS': ['temp']}})
    response = client.post('/ajax/charts', json={'CHARTS__CONFIG': json.dumps(settings)})
    assert response.status_code == expected
    save = application.extensions['chart_preview_save']
    if user == 'admin':
        assert configuration['CHARTS']['CUSTOM'] == []
        assert configuration['CHARTS']['OVERLAY_IDS'] == ['temp']
        assert configuration['CHARTS']['CUSTOM_SLOT_1'] == 'sensor_user_10'
        assert configuration['CCD_EXPOSURE_MAX'] == 42
        save.assert_called_once_with('admin', 'Updated chart settings')
    else:
        assert configuration == previous
        save.assert_not_called()


@pytest.mark.parametrize('payload', [None, [], {}, {'CHARTS__CONFIG': '{broken'},
    {'CHARTS__CONFIG': json.dumps({'OVERLAY_IDS': ['histogram']})}])
def test_chart_only_save_rejects_invalid_payloads_without_mutating_configuration(payload):
    application = create_chart_preview()
    previous = json.loads(json.dumps(application.extensions['chart_preview_config']))
    response = application.test_client().post('/ajax/charts', json=payload)
    assert response.status_code == 400
    assert application.extensions['chart_preview_config'] == previous
    application.extensions['chart_preview_save'].assert_not_called()


def test_chart_only_save_keeps_csrf_protection_and_supports_login_disabled_installations():
    from itsdangerous import URLSafeTimedSerializer

    application = create_chart_preview(csrf_enabled=True)
    client = application.test_client()
    settings = json.dumps(chart_configuration({'CHARTS': {'CUSTOM': []}}))
    assert client.post('/ajax/charts', json={'CHARTS__CONFIG': settings}).status_code == 400
    application.extensions['chart_preview_save'].assert_not_called()
    with client.session_transaction() as session:
        session['csrf_token'] = 'chart-session-token'
    token = URLSafeTimedSerializer(application.secret_key, salt='wtf-csrf-token').dumps('chart-session-token')
    assert client.post('/ajax/charts', json={'CHARTS__CONFIG': settings, 'csrf_token': token}).status_code == 400
    assert client.post('/ajax/charts', json={'CHARTS__CONFIG': settings, 'csrf_token': token},
                       headers={'X-CSRFToken': token}).status_code == 200
    application.extensions['chart_preview_save'].assert_called_once_with('system', 'Updated chart settings')


def test_chart_only_save_restores_previous_settings_when_persistence_fails():
    from indi_allsky.exceptions import ConfigSaveException

    application = create_chart_preview(save_error=ConfigSaveException('Save failed'))
    previous = json.loads(json.dumps(application.extensions['chart_preview_config']))
    settings = json.dumps(chart_configuration({'CHARTS': {'CUSTOM': []}}))
    response = application.test_client().post('/ajax/charts', json={'CHARTS__CONFIG': settings})
    assert response.status_code == 400
    assert response.json == {'form_global': ['Save failed']}
    assert application.extensions['chart_preview_config'] == previous


@pytest.mark.parametrize('browser, saved', [(True, False), (False, True), (True, True), (False, False)])
def test_on_image_chart_save_passes_actual_persistence_validation(browser, saved):
    application = create_chart_preview()
    configuration = application.extensions['chart_preview_config']
    save = application.extensions['chart_preview_save']
    settings = chart_configuration({'CHARTS': {'CUSTOM': [{'id': 'sky', 'source': 'sensor_user_0'}],
                                               'VISIBLE_IDS': ['sky'], 'OVERLAY_IDS': ['sky'] if browser else [],
                                               'SAVED_IMAGE_IDS': ['sky'] if saved else []}})
    response = application.test_client().post('/ajax/charts', json={'CHARTS__CONFIG': json.dumps(settings)})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert configuration['CHARTS']['CUSTOM'] == settings['CUSTOM']
    assert configuration['CHARTS']['VISIBLE_IDS'] == ['sky']
    assert configuration['CHARTS']['OVERLAY_IDS'] == (['sky'] if browser else [])
    assert configuration['CHARTS']['SAVED_IMAGE_IDS'] == (['sky'] if saved else [])
    save.assert_called_once_with('system', 'Updated chart settings')
    latest = application.test_client().get('/latest').get_data(as_text=True)
    assert ('data-chart-options="chart-overlay-options"' in latest) is browser
    if browser:
        assert 'data-saved-charts="{0}"'.format('true' if saved else 'false') in latest
    image = application.test_client().get('/image.jpg')
    assert image.status_code == 200
    assert (image.data != (ROOT / 'content/20210421_043940.jpg').read_bytes()) is saved


@pytest.mark.parametrize('reload', [None, False, True])
def test_chart_save_reloads_capture_only_when_requested(reload):
    application = create_chart_preview()
    payload = {'CHARTS__CONFIG': json.dumps(chart_configuration({'CHARTS': {'CUSTOM': []}}))}
    if reload is not None:
        payload['RELOAD_ON_SAVE'] = reload
    response = application.test_client().post('/ajax/charts', json=payload)
    assert response.status_code == 200
    session = application.extensions['chart_preview_db_session']
    tasks = application.extensions['chart_preview_tasks']
    state = application.extensions['chart_preview_state']
    if reload:
        state.setState.assert_called_once_with('STATUS', 'reloading')
        tasks.assert_called_once_with(queue='main', state='manual', priority=100, data={'action': 'reload'})
        session.add.assert_called_once()
        assert session.add.call_args.args[0].data == {'action': 'reload'}
        session.commit.assert_called_once()
        assert 'Reloading indi-allsky service' in response.json['success-message']
    else:
        state.setState.assert_not_called()
        tasks.assert_not_called()
        session.commit.assert_not_called()


@pytest.mark.parametrize('reload', ['false', 1, None, {}])
def test_chart_save_rejects_non_boolean_reload_values(reload):
    application = create_chart_preview()
    response = application.test_client().post('/ajax/charts', json={
        'CHARTS__CONFIG': json.dumps(chart_configuration({})), 'RELOAD_ON_SAVE': reload})
    assert response.status_code == 400
    assert 'RELOAD_ON_SAVE' in response.json
    application.extensions['chart_preview_save'].assert_not_called()
    application.extensions['chart_preview_tasks'].assert_not_called()


def test_disabling_saved_charts_reloads_capture_and_keeps_browser_chart():
    application = create_chart_preview()
    client = application.test_client()
    settings = chart_configuration(application.extensions['chart_preview_config'])
    settings['OVERLAY_IDS'] = ['custom_0']
    settings['SAVED_IMAGE_IDS'] = ['custom_0']
    response = client.post('/ajax/charts', json={'CHARTS__CONFIG': json.dumps(settings)})
    assert response.status_code == 200
    original = (ROOT / 'content/20210421_043940.jpg').read_bytes()
    assert client.get('/image.jpg').data != original

    settings['SAVED_IMAGE_IDS'] = []
    response = client.post('/ajax/charts', json={
        'CHARTS__CONFIG': json.dumps(settings), 'RELOAD_ON_SAVE': True})
    assert response.status_code == 200
    application.extensions['chart_preview_tasks'].assert_called_once_with(
        queue='main', state='manual', priority=100, data={'action': 'reload'})
    assert client.get('/image.jpg').data == original
    latest = client.get('/latest').get_data(as_text=True)
    assert 'data-saved-charts="false"' in latest
    assert 'data-chart-options="chart-overlay-options"' in latest


def test_failed_chart_save_does_not_reload_capture():
    from indi_allsky.exceptions import ConfigSaveException

    application = create_chart_preview(save_error=ConfigSaveException('Save failed'))
    response = application.test_client().post('/ajax/charts', json={
        'CHARTS__CONFIG': json.dumps(chart_configuration({})), 'RELOAD_ON_SAVE': True})
    assert response.status_code == 400
    application.extensions['chart_preview_tasks'].assert_not_called()
    application.extensions['chart_preview_state'].setState.assert_not_called()


def test_real_chart_templates_render_and_preview_settings_round_trip():
    client = create_chart_preview().test_client()
    for path in ('/settings', '/charts', '/latest', '/canvas'):
        response = client.get(path)
        assert response.status_code == 200, response.data
        assert b'CHARTS__CONFIG' in response.data if path == '/settings' else b'data-chart-stream' in response.data
        if path == '/latest':
            assert b"onload=\"this.style.opacity='1';\"" in response.data
            assert b"addEventListener('load'," in response.data
            assert b"document.getElementById('latest-image').onload" not in response.data
    settings = chart_configuration({'CHARTS': {'CUSTOM': [], 'OVERLAY_IDS': ['temp'], 'VISIBLE_IDS': []}})
    assert client.post('/settings', json={'CHARTS__CONFIG': json.dumps(settings)}).status_code == 200
    assert b'"OVERLAY_IDS": ["temp"]' in client.get('/settings').data.replace(b'&#34;', b'"')
    assert client.post('/settings', json={'CHARTS__CONFIG': '{broken'}).status_code == 400