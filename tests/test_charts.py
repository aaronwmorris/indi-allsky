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
from indi_allsky.charts import build_chart_data


ROOT = Path(__file__).resolve().parents[1]


def production_chart_handler(config, readings, args):
    from sqlalchemy import and_, column, func

    tree = ast.parse((ROOT / 'indi_allsky/flask/views.py').read_text(encoding='utf-8'))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'JsonChartView')
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in ('getChartData', 'get_objects')]
    query = MagicMock()
    for name in ('add_columns', 'join', 'filter', 'order_by'):
        getattr(query, name).return_value = query
    query.__iter__.side_effect = lambda: iter(readings)
    query.first.return_value = None
    image = SimpleNamespace(query=query, **{name: column(name) for name in (
        'createDate', 'sqm', 'stars', 'temp', 'gain', 'exposure', 'detections', 'data', 'camera')})
    namespace = {'request': SimpleNamespace(args=args), 'datetime': datetime, 'timedelta': timedelta,
                 'IndiAllSkyDbImageTable': image, 'IndiAllSkyDbCameraTable': SimpleNamespace(id=column('camera_id')),
                 'and_': and_, 'func': func, 'build_chart_data': build_chart_data, 'chart_definitions': chart_definitions}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'production-chart-handler', 'exec'), namespace)
    handler = SimpleNamespace(indi_allsky_config=config, camera=SimpleNamespace(local=True, data={'sensor_user_0': 'Sky temperature'}),
                              chart_history_seconds=900, camera_now=datetime(2026, 10, 4, 20, 45), cameraSetup=lambda **kwargs: None)
    handler.getChartData = lambda *values: namespace['getChartData'](handler, *values)
    return namespace['get_objects'](handler), query


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
                         'OVERLAY_IDS': ['local_sky'], 'VISIBLE_IDS': ['temp', 'local_sky']}}
    metadata = {'chart_definitions': [{'id': 'remote_sky', 'source': 'sensor_user_12'}]}
    settings = chart_configuration(config, metadata, is_local=False)
    assert settings['OVERLAY_IDS'] == ['remote_sky']
    assert settings['VISIBLE_IDS'] == ['temp', 'remote_sky']


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


def test_legacy_aurora_sources_are_preserved():
    assert validate_custom_charts([{'id': 'aurora', 'source': 'kpindex'}])[0]['source'] == 'kpindex'


def test_default_preferences_preserve_existing_charts_and_disable_overlays():
    settings = chart_configuration({})
    assert len(settings['VISIBLE_IDS']) == 16
    assert settings['OVERLAY_IDS'] == []


def test_chart_and_image_visibility_are_independent():
    settings = validate_chart_configuration({'CUSTOM': [], 'VISIBLE_IDS': [], 'OVERLAY_IDS': ['stars', 'temp']})
    assert settings['VISIBLE_IDS'] == []
    assert settings['OVERLAY_IDS'] == ['stars', 'temp']


@pytest.mark.parametrize('settings', [
    {'OVERLAY_IDS': ['histogram']}, {'OVERLAY_IDS': ['stars', 'stars']},
    {'VISIBLE_IDS': ['unknown']}, {'OVERLAY_WIDTH': 999}, {'OVERLAY_TOP': -1},
    {'OVERLAY_HISTORY_SECONDS': 86401}, {'OVERLAY_OPACITY': True},
])
def test_invalid_preferences_are_rejected(settings):
    with pytest.raises(ValueError):
        validate_chart_configuration(settings)


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
    assert len(response['chart_data']) == 16
    assert response['message'] == 'No chart data in history range'
    query.first.assert_not_called()


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


def create_chart_preview():
    from flask import Blueprint, Flask, jsonify, render_template, render_template_string, request, send_file
    from jinja2 import ChoiceLoader, DictLoader
    from wtforms import Form, HiddenField, SelectField
    from indi_allsky.charts import BUILTIN_CHARTS, MAX_CUSTOM_CHARTS

    templates = ROOT / 'indi_allsky/flask/templates'
    static = ROOT / 'indi_allsky/flask/static'
    application = Flask('chart-preview', template_folder=str(templates), static_folder=None)
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

    class EditorForm(Form):
        CHARTS__CONFIG = HiddenField()
        CHARTS__CUSTOM_SLOT_1 = SelectField(choices=choices)

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

    @blueprint.route('/js/charts', endpoint='js_chart_view')
    def chart_response():
        readings = [SimpleNamespace(createDate=datetime(2026, 10, 4, 20, 0) + timedelta(seconds=index * 25),
                    temp=12 + index / 50, stars_rolling=40 + index % 12, jsqm=100 + index % 7, gain=50,
                    exposure=15, detections=index % 6 == 0,
                    data={'sensor_user_{0}'.format(source): -27 + index / 20 if source == 0 else source * 2 + index % 7 for source in range(11)})
                    for index in range(36)]
        response, query = production_chart_handler(configuration, readings, dict(request.args))
        if request.args.get('histogram', '1') == '1':
            response['chart_data']['histogram']['gray'] = [{'x': str(index), 'y': 100 - abs(index - 70)} for index in range(100)]
        return jsonify(response)

    @blueprint.route('/js/latest', endpoint='js_latest_image_view')
    def latest_response():
        return jsonify(latest_image={'url': '/image.jpg', 'message': '2026-10-04 20:45 | Exposure 15s | Gain 50'})

    @blueprint.route('/image.jpg')
    def image_response():
        return send_file(ROOT / 'content/20210421_043940.jpg')

    application.register_blueprint(blueprint)
    return application


def test_real_chart_templates_render_and_preview_settings_round_trip():
    client = create_chart_preview().test_client()
    for path in ('/settings', '/charts', '/latest', '/canvas'):
        response = client.get(path)
        assert response.status_code == 200, response.data
        assert b'CHARTS__CONFIG' in response.data if path == '/settings' else b'data-chart-stream' in response.data
    settings = chart_configuration({'CHARTS': {'CUSTOM': [], 'OVERLAY_IDS': ['temp'], 'VISIBLE_IDS': []}})
    assert client.post('/settings', json={'CHARTS__CONFIG': json.dumps(settings)}).status_code == 200
    assert b'"OVERLAY_IDS": ["temp"]' in client.get('/settings').data.replace(b'&#34;', b'"')
    assert client.post('/settings', json={'CHARTS__CONFIG': '{broken'}).status_code == 400