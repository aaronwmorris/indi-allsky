from pathlib import Path

import pytest
from jinja2 import DictLoader
from jinja2 import Environment


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPOSITORY_ROOT.joinpath(
    'indi_allsky',
    'flask',
    'templates',
    'darks.html',
)


def _render_builder(
    action,
    *,
    stored_dark_count,
    stored_bpm_count,
    ready_count,
    suggested_count,
    target_count=17,
):
    environment = Environment(loader=DictLoader({
        'base.html': (
            '{% block title %}{% endblock %}'
            '{% block head %}{% endblock %}'
            '{% block content %}{% endblock %}'
        ),
        'darks.html': TEMPLATE_PATH.read_text(encoding='utf-8'),
    }))
    environment.globals.update({
        'url_for': lambda *args, **kwargs: '/',
        'csrf_token': lambda: 'test-token',
    })
    preview = {
        'strategy': 'complete',
        'capture_mode': 'single',
        'estimated_time': '1h 00m 00s',
        'estimated_library_storage': '500 MiB',
        'exposure_max': 30,
        'exposure_step': 5,
        'temperature_source': 'auto',
        'temperature_target': None,
        'target_count': suggested_count,
        'groups': [],
    }
    analysis = {
        'available': True,
        'suggested_action': action,
        'suggested_target_count': suggested_count,
        'estimated_time': '1h 00m 00s',
        'stored_dark_count': stored_dark_count,
        'stored_bpm_count': stored_bpm_count,
        'usable_dark_count': stored_dark_count,
        'usable_bpm_count': stored_bpm_count,
        'structural_ready_target_count': ready_count,
        'target_count': target_count,
        'mode': 'Exposure priority',
        'gain_policy_summary': 'Balanced gain spacing',
        'binnings': [1],
        'bit_depths': [16],
        'temperature_ready_target_count': ready_count,
        'temperature_checked': True,
        'temperature': 20,
        'temperature_status_label': 'Covered',
        'target_temperatures': [],
        'counts': {
            'exact': ready_count,
            'acceptable': 0,
            'coarse': 0,
            'temperature': 0,
            'incompatible': 0,
            'missing': target_count - ready_count,
        },
        'completion_target_count': suggested_count,
        'refresh_target_count': target_count,
        'rebuild_target_count': target_count,
        'warnings': [],
        'groups': [],
        'temperature_reading': None,
    }
    return environment.get_template('darks.html').render({
        'website_title': 'indi-allsky',
        'page_title': 'Dark Frames',
        'camera_id': 1,
        'dark_execution_preview': preview,
        'dark_analysis': analysis,
        'dark_temperature_sources': [],
        'dark_automation_can_run': True,
        'dark_automation_task_id': None,
        'dark_library_can_manage': False,
        'dark_library_task_active': False,
        'dark_library_catalog': {'libraries': [], 'entry_count': 0},
        'darkframe_list': [],
        'bpm_list': [],
        'camera_name': 'Test Camera',
    })


@pytest.mark.parametrize(
    'action, stored_dark_count, stored_bpm_count, ready_count, suggested_count, title',
    (
        ('rebuild', 0, 0, 0, 17, 'Build your first dark library'),
        ('complete', 20, 20, 5, 12, 'Add the missing dark settings'),
        ('temperature', 20, 20, 17, 17, 'Your library is complete'),
        ('none', 20, 20, 17, 0, 'Your dark library is ready'),
        ('rebuild', 20, 0, 0, 17, 'Build a compatible dark library'),
    ),
)
def test_builder_explains_each_library_state(
    action,
    stored_dark_count,
    stored_bpm_count,
    ready_count,
    suggested_count,
    title,
):
    html = _render_builder(
        action,
        stored_dark_count=stored_dark_count,
        stored_bpm_count=stored_bpm_count,
        ready_count=ready_count,
        suggested_count=suggested_count,
    )

    assert title in html
    assert 'A setting combines gain, exposure, binning and data depth.' in html
    assert 'One master set creates one master dark and one matching bad-pixel map' in html \
        if suggested_count else 'No action is required.' in html
    assert 'Preview 2026.08.21.2' in html
    if suggested_count:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4"' in html
    else:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4 tw:hidden"' in html
