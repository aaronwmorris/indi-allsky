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
    temperature_ready_count=None,
    automation_can_run=True,
    config_requires_reload=False,
):
    if temperature_ready_count is None:
        temperature_ready_count = ready_count

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
        'temperature_range': 5.0,
        'temperature_range_source': 'legacy_default',
        'temperature_source': 'auto',
        'temperature_delta': 5.0,
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
        'mode_description': (
            'indi-allsky lengthens exposure first, then changes gain at maximum exposure.'
        ),
        'gain_policy_summary': 'Balanced gain spacing',
        'temperature_range': 5.0,
        'binnings': [1],
        'bit_depths': [16],
        'temperature_ready_target_count': temperature_ready_count,
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
        'dark_automation_can_run': automation_can_run,
        'dark_config_requires_reload': config_requires_reload,
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
    assert 'Preview 2026.08.21.7' in html
    assert 'lengthens exposure first, then changes gain at maximum exposure' in html
    assert 'masters captured from 15.0°C through 25.0°C' in html
    assert 'The ±5°C value is a distance from this reading' in html
    assert 'Temperature is checked separately for each gain/exposure setting' in html
    assert 'Normal drift during capture can therefore leave only some settings' in html
    assert 'More frames reduce random noise' in html
    assert 'Starting at the maximum, adds another exposure length' in html
    if suggested_count:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4"' in html
    else:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4 tw:hidden"' in html


def test_partial_library_separates_structural_and_temperature_coverage():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=17,
        temperature_ready_count=0,
    )

    assert (
        'Across all stored temperature layers, compatible dark-and-map pairs cover '
        '5 of 17 recommended camera settings.'
    ) in html
    assert (
        'At the configured or current temperature, 0 of 17 are ready, so the '
        'prepared job contains 17 new master sets for this temperature layer.'
    ) in html
    assert '5 of 17 settings covered across all temperatures' in html
    assert '0 of 17 are ready at the configured or current temperature.' in html


def test_advanced_options_use_width_safe_two_column_layout():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )
    advanced = html.split('id="dark-advanced-options"', 1)[1].split(
        'id="dark-run-instructions"',
        1,
    )[0]

    assert 'tw:grid-cols-1 tw:sm:grid-cols-2 tw:gap-3 tw:min-w-0' in advanced
    assert 'tw:sm:grid-cols-3' not in advanced
    assert 'tw:lg:grid-cols-3' not in advanced
    assert 'tw:w-full tw:max-w-full tw:min-w-0' in advanced
    assert 'target cells' not in advanced


def test_advanced_plan_validation_blocks_invalid_capture_requests():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'id="dark-plan-validation"' in html
    assert 'Review the advanced plan' in html
    assert 'Choose between 3 and 50 source frames per master.' in html
    assert 'A selected gain is below the camera minimum.' in html
    assert 'Dark exposure lengths must be greater than zero.' in html
    assert 'const planIsValid = updateDarkPlanValidation(masterCount, true);' in html
    assert '&& planIsValid' in html
    assert 'if (!updateDarkPlanValidation(undefined, false))' in html
    assert 'if (!updateDarkPlanValidation(undefined, true))' in html


def test_temperature_series_summary_pluralizes_one_set():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert "const temperatureSetText = (count) => count + ' temperature set'" in html
    assert "' across ' + temperatureSetText(temperatureSetCount)" in html
    assert "' across ' + temperatureSetCount + ' sets'" not in html


def test_advanced_temperature_controls_distinguish_matching_from_capture_step():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'id="dark-temperature-range"' in html
    assert 'Recommend another layer beyond' in html
    assert 'The initial 5°C value is the legacy fallback' in html
    assert 'does not infer this preference from their spacing' in html
    assert 'id="dark-temperature-delta"' in html
    assert 'Temperature-series step' in html
    assert 'It is independent of the recommendation distance above' in html
    assert 'Starting this run saves the override as this camera' in html


def test_stale_service_configuration_explains_why_capture_is_unavailable():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
        automation_can_run=False,
        config_requires_reload=True,
    )

    assert 'the capture service is still using an older one' in html
    assert 'Reload the service, return here, and review the updated plan.' in html
    assert 'No dark run can start while the two configurations differ.' in html
