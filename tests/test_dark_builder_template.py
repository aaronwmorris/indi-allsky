from datetime import datetime
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
    library_can_manage=False,
    library_catalog=None,
    darkframe_list=None,
    bpm_list=None,
    darkframe_summary=None,
    bpm_summary=None,
):
    if temperature_ready_count is None:
        temperature_ready_count = ready_count
    if library_catalog is None:
        library_catalog = {
            'cameras': [],
            'camera_count': 0,
            'entry_count': 0,
            'size': '0 B',
        }
    if darkframe_list is None:
        darkframe_list = []
    if bpm_list is None:
        bpm_list = []
    empty_summary = {
        'total': 0,
        'active': 0,
        'inactive': 0,
        'unpaired': 0,
        'compatible': 0,
        'missing_files': 0,
    }
    if darkframe_summary is None:
        darkframe_summary = empty_summary
    if bpm_summary is None:
        bpm_summary = empty_summary

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
        'strategy': action if action in ('complete', 'rebuild') else 'complete',
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
        'dark_library_can_manage': library_can_manage,
        'dark_library_task_active': False,
        'dark_library_catalog': library_catalog,
        'darkframe_list': darkframe_list,
        'bpm_list': bpm_list,
        'darkframe_summary': darkframe_summary,
        'bpm_summary': bpm_summary,
        'camera_name': 'Test Camera',
    })


@pytest.mark.parametrize(
    'action, stored_dark_count, stored_bpm_count, ready_count, suggested_count, title',
    (
        ('rebuild', 0, 0, 0, 17, 'Build or rebuild selected profiles'),
        ('complete', 20, 20, 5, 12, 'Fill gaps only'),
        ('temperature', 20, 20, 17, 17, 'Fill gaps only'),
        ('none', 20, 20, 17, 0, 'No library update needed'),
        ('rebuild', 20, 0, 0, 17, 'Build or rebuild selected profiles'),
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
    assert 'One master set is a master dark and matching bad-pixel map' in html
    assert 'One master set creates one master dark and one matching bad-pixel map' in html \
        if suggested_count else 'No action is required.' in html
    assert 'Preview 2026.08.23.5' in html
    assert 'lengthens exposure first, then changes gain at maximum exposure' in html
    assert 'masters from 15.0°C to 25.0°C count as matched' in html
    assert 'Every required master set is checked separately, so capture drift may leave only some' in html
    assert 'Each master set uses this many images to build one dark and one bad-pixel map.' in html
    assert 'Step down from the longest exposure by this amount' in html
    if suggested_count:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4"' in html
    else:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4 tw:hidden"' in html


@pytest.mark.parametrize(
    'action, ready_count, suggested_count, title, recommended_option',
    (
        ('complete', 5, 12, 'Fill gaps only', 'dark-completion-option'),
        ('temperature', 17, 17, 'Fill gaps only', 'dark-completion-option'),
        ('rebuild', 0, 17, 'Build or rebuild selected profiles', 'dark-rebuild-option'),
        ('none', 17, 0, 'No library update needed', None),
    ),
)
def test_recommended_library_update_uses_the_same_name_everywhere(
    action,
    ready_count,
    suggested_count,
    title,
    recommended_option,
):
    html = _render_builder(
        action,
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=ready_count,
        suggested_count=suggested_count,
    )
    recommendation = html.split('id="dark-recommendation-card"', 1)[1].split(
        'id="dark-recommendation-explanation"',
        1,
    )[0]
    update_choices = html.split('Library update choices', 1)[1].split(
        'id="dark-planning-warnings"',
        1,
    )[0]

    title_markup = recommendation.split('id="dark-recommendation-title"', 1)[1].split(
        '</h5>',
        1,
    )[0]
    strategy_options = html.split('id="dark-strategy"', 1)[1].split('</select>', 1)[0]
    assert title in title_markup
    if recommended_option:
        assert f'id="{recommended_option}" class="dark-update-option dark-update-option--recommended' in update_choices
        assert f'{title} · recommended</option>' in strategy_options
        assert 'The choice made by the recommendation above is highlighted.' in update_choices
    else:
        assert 'dark-update-option--recommended' not in update_choices
        assert ' · recommended</option>' not in strategy_options
        assert 'No option is highlighted because no library update is recommended.' in update_choices


def test_library_tabs_show_health_pairing_compatibility_and_temperature_range():
    row_base = {
        'createDate': datetime(2026, 8, 21, 12, 0, 0),
        'bitdepth': 16,
        'gain': 100,
        'exposure': 30,
        'binmode': 1,
        'width': 100,
        'height': 50,
        'adu': 123.4,
        'hot_pixels': 7,
        'url': '/download',
        'size_mb': 1.5,
        'method': 'sigmaclip',
    }
    dark = {
        **row_base,
        'id': 101,
        'active': True,
        'exists': True,
        'temp': 20.0,
        'temperature_min': 15.0,
        'temperature_max': 25.0,
        'configuration_compatible': True,
        'partner_id': 201,
        'partner_active': False,
        'partner_exists': False,
    }
    bpm = {
        **row_base,
        'id': 201,
        'active': False,
        'exists': False,
        'temp': None,
        'temperature_min': None,
        'temperature_max': None,
        'configuration_compatible': False,
        'partner_id': 101,
        'partner_active': True,
        'partner_exists': True,
    }
    dark_summary = {
        'total': 1,
        'active': 1,
        'inactive': 0,
        'unpaired': 0,
        'compatible': 1,
        'missing_files': 0,
    }
    bpm_summary = {
        'total': 1,
        'active': 0,
        'inactive': 1,
        'unpaired': 0,
        'compatible': 0,
        'missing_files': 1,
    }

    html = _render_builder(
        'none',
        stored_dark_count=1,
        stored_bpm_count=1,
        ready_count=17,
        suggested_count=0,
        darkframe_list=[dark],
        bpm_list=[bpm],
        darkframe_summary=dark_summary,
        bpm_summary=bpm_summary,
    )

    assert 'aria-label="Filter master darks"' in html
    assert 'aria-label="Filter bad-pixel maps"' in html
    assert 'data-filter="inactive"' in html
    assert 'data-filter="unpaired"' in html
    assert 'data-filter="compatible"' in html
    assert 'data-filter="missing-file"' in html
    assert html.count('Current setup compares image size, binning and bit depth') == 2
    assert html.count('Choose a summary card to show only those entries.') == 2
    assert html.count('>Interactive</span>') == 2
    assert html.count('>All entries</span>') == 2
    assert html.count('>Matches setup</span>') == 2
    assert 'data-target-tab="tab-bpm" data-partner-id="201"' in html
    assert 'data-target-tab="tab-darks" data-partner-id="101"' in html
    assert 'Map #201' in html
    assert 'Dark #101' in html
    assert 'usable 15.0 to 25.0°C' in html
    assert '>Matches</span>' in html
    assert '>Different</span>' in html
    assert html.count('>Current setup</th>') == 2
    assert 'data-search="missing-file"' in html
    assert '>Missing file</span>' in html
    assert 'id="darks-table-filter-status"' in html
    assert 'id="bpm-table-filter-status"' in html
    assert html.count('>Show all entries</button>') == 2
    assert html.count('inactive entries remain stored but are not selected') == 2

    dark_table = html.split('<table id="darks-table"', 1)[1].split('</table>', 1)[0]
    bpm_table = html.split('<table id="bpm-table"', 1)[1].split('</table>', 1)[0]
    assert dark_table.split('</thead>', 1)[0].count('<th ') == 15
    assert bpm_table.split('</thead>', 1)[0].count('<th ') == 15


def test_library_tables_drop_secondary_columns_before_calibration_identity():
    html = _render_builder(
        'none',
        stored_dark_count=0,
        stored_bpm_count=0,
        ready_count=17,
        suggested_count=0,
    )

    breakpoints = (
        '@media (max-width: 1450px)',
        '@media (max-width: 1200px)',
        '@media (max-width: 1050px)',
        '@media (max-width: 950px)',
        '@media (max-width: 850px)',
        '@media (max-width: 720px)',
        '@media (max-width: 560px)',
    )
    assert [html.index(breakpoint) for breakpoint in breakpoints] == sorted(
        html.index(breakpoint) for breakpoint in breakpoints
    )
    assert '.dark-col-diagnostic {' in html
    assert '.dark-col-date {' in html
    assert '.dark-col-process {' in html
    assert '.dark-col-file {' in html
    assert '.dark-col-image-profile {' in html
    assert '.dark-col-compatibility {' in html
    assert '.dark-col-id {' in html
    assert '.dark-partner-state {' in html
    assert 'overflow-x: auto;' in html
    assert 'grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr));' in html
    assert "const darkLibraryFilterColumns = {" in html
    assert 'active: 2' in html
    assert 'partner: 3' in html
    assert 'compatible: 4' in html
    assert 'file: 12' in html
    assert "order: [[6, 'desc'], [7, 'desc'], [1, 'desc']]" in html
    assert ".removeClass('tw:hidden')" in html
    assert ".text('Showing linked ' + entryLabel + ' #' + focusedId + '.')" in html
    assert "applyDarkLibraryFilter($(this).data('table-id'), 'all');" in html


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
        '5 of 17 recommended master sets.'
    ) in html
    assert (
        'At the configured or current temperature, 0 of 17 are ready, so the '
        'prepared job contains 17 new master sets for this temperature layer.'
    ) in html
    assert '5 of 17 master sets covered across all temperatures' in html
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


def test_capture_groups_reflow_as_cards_instead_of_squeezing_table_columns():
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

    assert 'id="dark-plan-groups" role="list" aria-label="Capture groups"' in advanced
    assert '<table' not in advanced
    assert 'grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));' in html
    assert '<section class="dark-plan-row ' in html
    assert 'class="dark-plan-row-fields"' in html
    assert 'Image output and temperature target' in html
    assert 'tw:min-w-48' not in html


def test_library_removal_explains_temperature_groups_and_master_status():
    library_catalog = {
        'camera_count': 1,
        'entry_count': 4,
        'size': '4.0 KiB',
        'cameras': [{
            'id': 1,
            'name': 'Test Camera',
            'friendly_name': 'Test Camera',
            'current': True,
            'dark_count': 2,
            'bpm_count': 2,
            'master_set_count': 2,
            'active_master_set_count': 1,
            'inactive_master_set_count': 1,
            'mixed_master_set_count': 0,
            'inactive_count': 2,
            'inactive_selection': {'dark_ids': [2], 'bpm_ids': [12]},
            'selection': {'dark_ids': [1, 2], 'bpm_ids': [11, 12]},
            'size': '4.0 KiB',
            'temperature_range': 5.0,
            'profiles': [{
                'width': 100,
                'height': 50,
                'binning': 1,
                'bit_depth': 16,
                'entry_count': 4,
                'master_set_count': 2,
                'active_master_set_count': 1,
                'inactive_master_set_count': 1,
                'mixed_master_set_count': 0,
                'size': '4.0 KiB',
                'selection': {'dark_ids': [1, 2], 'bpm_ids': [11, 12]},
                'layers': [{
                    'temperature_label': '42.1 to 43.2°C',
                    'active_master_set_count': 1,
                    'inactive_master_set_count': 1,
                    'mixed_master_set_count': 0,
                    'master_set_count': 2,
                    'entry_count': 4,
                    'size': '4.0 KiB',
                    'latest_date': None,
                    'selection': {'dark_ids': [1, 2], 'bpm_ids': [11, 12]},
                    'master_sets': [{
                        'gain': 10,
                        'exposure': 30,
                        'temperature': 43.2,
                        'paired': True,
                        'status': 'active',
                        'size': '2.0 KiB',
                        'selection': {'dark_ids': [1], 'bpm_ids': [11]},
                    }, {
                        'gain': 20,
                        'exposure': 30,
                        'temperature': 42.1,
                        'paired': True,
                        'status': 'inactive',
                        'size': '2.0 KiB',
                        'selection': {'dark_ids': [2], 'bpm_ids': [12]},
                    }],
                }],
            }],
        }],
    }
    html = _render_builder(
        'none',
        stored_dark_count=2,
        stored_bpm_count=2,
        ready_count=17,
        suggested_count=0,
        library_can_manage=True,
        library_catalog=library_catalog,
    )

    assert 'uses a ±5°C Allowed temperature difference' in html
    assert '42.1 to 43.2°C' in html
    assert '2 master sets: 1 active, 1 inactive' in html
    assert '>Active</span>' in html
    assert '>Inactive</span>' in html
    assert 'Delete temperature group…' in html
    assert 'Delete temperature layer…' not in html

    recommendation = html.split('aria-labelledby="dark-recommendation-title"', 1)[1].split(
        'id="dark-recommendation-explanation"',
        1,
    )[0]
    assert 'dark-recommendation-summary' in recommendation
    assert recommendation.count('dark-recommendation-summary-cell') == 3
    assert 'tw:divide-y' not in recommendation
    assert 'tw:divide-x' not in recommendation

    maintenance = html.split('id="dark-library-maintenance"', 1)[1].split(
        '<!-- Dark Frames Tab Panel -->',
        1,
    )[0]
    assert 'dark-builder-step-header' in maintenance
    assert 'dark-builder-step-marker dark-builder-step-marker--danger' in maintenance
    assert 'Library tools' in maintenance
    assert 'dark-library-maintenance-body' in maintenance
    assert 'Stored calibration files' in maintenance
    assert 'Storage used' in maintenance
    assert maintenance.count('dark-library-scope-row') >= 5
    assert maintenance.count('dark-library-action-column') >= 5
    assert 'Delete complete camera library…' in maintenance
    assert 'dark-remove-selection tw:btn tw:btn-sm' in maintenance
    assert 'Select several master sets' not in maintenance
    assert 'Select one or more master sets to manage them together.' in maintenance
    assert 'Actions appear at the bottom of the screen.' in maintenance
    assert maintenance.count('dark-library-master-checkbox') == 2
    assert 'dark-library-batch-toolbar' not in maintenance
    assert 'id="dark-library-selection-bar"' in maintenance
    assert 'id="dark-library-selection-camera"' in maintenance
    assert 'id="dark-library-selection-summary"' in maintenance
    assert 'id="dark-library-clear-selection"' in maintenance
    assert 'id="dark-library-deactivate-selected"' in maintenance
    assert 'id="dark-library-activate-selected"' in maintenance
    assert 'id="dark-library-delete-selected"' in maintenance
    assert 'Deactivate (exclude from calibration)…' in maintenance
    assert 'Delete selected master sets…' in maintenance
    assert "'Delete ' + masterCount + ' ' + masterLabel + '…'" in html
    assert 'Activate (make eligible again)…' in maintenance
    assert 'Clear this selection before choosing another camera.' in maintenance
    assert 'id="dark-eligibility-confirmation"' in maintenance
    assert 'Deactivation leaves the files stored and can be reversed' in maintenance

    assert '.dark-library-scope-row {' in html
    assert 'grid-template-columns: minmax(0, 1fr) minmax(13rem, 16rem);' in html
    assert '#dark-library-maintenance > .dark-library-maintenance-body' in html
    assert 'background-color: color-mix(in oklab, var(--color-error) 5%, var(--color-base-100));' in html
    assert 'border-color: color-mix(in oklab, var(--color-error) 38%, var(--color-base-300));' in html
    assert 'background-color: color-mix(in oklab, var(--color-warning) 12%, var(--color-base-100));' in html
    assert 'id="dark-removal-confirmation-input" class="tw:input tw:input-bordered tw:input-error' in html
    assert '.dark-library-selection-bar {' in html
    assert 'position: fixed;' in html
    assert 'bottom: max(0.75rem, env(safe-area-inset-bottom));' in html
    assert '#dark-library-maintenance.dark-library-selection-active .dark-library-master-actions' in html
    assert '#dark-page-content.dark-library-selection-mode' in html
    assert 'function scheduleDarkSelectionBarLayout()' in html
    assert "'--dark-library-selection-center'" in html
    assert "'--dark-library-selection-height'" in html
    assert "document.getElementById('dark-library-maintenance') || page" in html
    assert '@container (max-width: 60rem)' in html
    assert 'function keepDarkSelectionRowVisible(checkbox)' in html
    assert 'initializeDarkSelectionBarLayout();' in html
    assert 'function updateDarkMarkedSelection(cameraId)' in html
    assert 'let activeDarkSelectionCameraId = null;' in html
    assert "activeDarkSelectionCameraId !== cameraId" in html
    assert "otherCamera = hasSelection" in html
    assert "toolbar.toggleClass('tw:hidden', !hasSelection);" in html
    assert 'const hasStagedSelection' in html
    assert 'const canRestore = !hasStagedSelection' in html
    assert 'function renderDarkCoverageImpact(selector, impact, fallbackMessage)' in html
    assert 'const darkIds = new Set();' in html
    assert 'const bpmIds = new Set();' in html
    assert "if (darkLibraryCanManage) {" in html


def test_non_config_admin_can_review_recommendation_but_not_capture_or_remove():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
        automation_can_run=False,
        library_can_manage=False,
    )

    assert 'An administrator can use guided capture for a local camera.' in html
    assert 'Library maintenance' not in html
    assert 'const darkAutomationCanRun = false;' in html
    assert 'const darkLibraryCanManage = false;' in html


def test_library_update_choices_have_distinct_capture_and_retirement_outcomes():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'Library update' in html
    assert '>Fill gaps only · recommended</option>' in html
    assert '>Refresh recommended master sets only</option>' in html
    assert '>Build or rebuild selected profiles</option>' in html
    assert '>Edit capture groups manually</option>' in html
    assert (
        "complete: 'Capture only uncovered master sets. Existing masters keep their active/inactive status.'"
    ) in html
    assert 'deactivate only older copies of those same gain/exposure combinations' in html
    assert 'including gains or exposures no longer recommended' in html
    assert 'Under Advanced options, choose <strong>Edit capture groups manually</strong>' in html
    assert 'to change which rows, gains or exposures will be captured' in html
    assert 'Advanced options → Library update' in html
    assert 'id="dark-completion-option" class="dark-update-option dark-update-option--recommended' in html
    assert 'id="dark-completion-option-badge" class="tw:badge tw:badge-primary tw:badge-sm">Recommended' in html
    assert 'Refresh recommended master sets only</strong> and <strong>Build or rebuild selected profiles</strong> both capture 17 master sets' in html
    assert 'Refresh replaces only those recommended sets' in html
    assert 'Build or rebuild also deactivates older extras' in html
    assert 'Inactive masters stay stored but are not used for calibration.' in html


def test_recommendation_origin_and_overviews_are_explicitly_labelled():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'How the recommended grid is built' in html
    assert 'The builder reads the relevant saved day, night, moon and SQM capture profiles.' in html
    assert 'Inputs used' in html
    assert 'Saved camera configuration' in html
    assert 'id="dark-saved-exposure-max">30 seconds</strong> (capped by the camera if necessary)' in html
    assert 'Strategy: <strong>Exposure priority</strong>' in html
    assert 'Library builder / user' in html
    assert 'id="dark-input-temperature-source">Automatic</strong>' in html
    assert 'id="dark-input-temperature-range">5</span>°C' in html
    assert 'id="dark-input-exposure-step">5</span> seconds' in html
    assert 'Step 1 supplies the first two values; Advanced options supplies the exposure interval' in html
    assert 'Where the inputs come from' not in html
    assert 'Camera-reported limits' not in html
    assert '1 second is always included' in html
    assert 'Duplicate combinations shared by several capture profiles count only once.' in html
    assert 'id="dark-recommendation-target-count">17</span> recommended master' in html
    assert 'A stored set can fall outside today’s recommendation' in html
    assert 'after changing a capture profile, gain strategy, longest exposure or exposure interval' in html
    assert 'This does not mean the stored set is damaged' in html
    assert 'Recommended master-set overview' in html
    assert 'This is the generated recommendation for the current camera and builder choices.' in html
    assert 'id="dark-recommendation-step-title" class="dark-builder-step-title">Review the recommendation' in html
    assert 'Recommended library update' in html
    assert 'Run the capture plan' in html
    assert 'The capture plan follows the recommendation above. If needed, you can customize it under Advanced options.' in html


def test_recalculated_plan_updates_every_recommendation_surface():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    expected_targets = (
        'dark-recommendation-title',
        'dark-recommendation-description',
        'dark-recommendation-badge',
        'dark-recommendation-structural-coverage',
        'dark-recommendation-temperature-coverage',
        'dark-recommendation-new-count',
        'dark-recommendation-new-note',
        'dark-coverage-exact',
        'dark-coverage-acceptable',
        'dark-coverage-coarse',
        'dark-coverage-temperature',
        'dark-coverage-incompatible',
        'dark-coverage-missing',
        'dark-completion-option-description',
        'dark-refresh-option-description',
        'dark-rebuild-option-description',
        'dark-update-choice-state',
        'dark-recommendation-overview-body',
        'dark-input-temperature-source',
        'dark-input-temperature-range',
        'dark-input-exposure-step',
    )
    for target in expected_targets:
        assert f'id="{target}"' in html

    assert 'function renderDarkRecommendation(plan)' in html
    assert 'const analysis = (plan || {}).analysis || {};' in html
    assert "$('#dark-recommendation-temperature-coverage')" in html
    assert "$('#dark-coverage-' + kind).text(Number(counts[kind]) || 0);" in html
    assert "const overviewBody = $('#dark-recommendation-overview-body');" in html
    assert "$('#dark-input-temperature-source').text(temperatureSourceLabel);" in html
    assert "$('#dark-input-temperature-range').text(temperatureRangeLabel);" in html
    assert "$('#dark-recommendation-exposure-step, #dark-input-exposure-step')" in html
    assert 'renderDarkRecommendation(plan);' in html


def test_guided_steps_and_maintenance_share_a_theme_aware_visual_system():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
        library_can_manage=True,
    )

    assert html.count('class="dark-builder-step"') == 3
    assert html.count('dark-builder-step-header') >= 4
    assert html.count('dark-builder-step-marker') >= 4
    assert 'class="dark-builder-step-eyebrow">Step 1' in html
    assert 'class="dark-builder-step-eyebrow">Step 2' in html
    assert 'class="dark-builder-step-eyebrow">Step 3' in html
    assert 'Set temperature matching' in html
    assert 'Review the recommendation' in html
    assert 'Run the capture plan' in html

    step_two = html.split('aria-labelledby="dark-recommendation-step-title"', 1)[1].split(
        'id="dark-capture-controls"',
        1,
    )[0]
    assert 'id="dark-recommendation-card"' in step_two
    assert 'id="dark-recommendation-explanation"' in step_two
    assert step_two.index('id="dark-recommendation-card"') \
        < step_two.index('id="dark-recommendation-explanation"')
    assert 'id="dark-recommendation-details"' not in html

    assert 'background-color: var(--color-base-100);' in html
    assert 'color-mix(in oklab, var(--color-success)' in html
    assert 'color-mix(in oklab, var(--color-warning)' in html
    assert 'color-mix(in oklab, var(--color-info)' in html
    assert 'color-mix(in oklab, var(--color-error)' in html
    assert 'dark-recommendation-state-success' in html
    assert 'dark-recommendation-state-warning' in html
    assert 'dark-recommendation-state-info' in html
    assert 'dark-coverage-card--success' in html
    assert 'dark-coverage-card--info' in html
    assert 'dark-coverage-card--warning' in html
    assert 'dark-coverage-card--error' in html
    assert 'dark-library-storage-summary' in html
    assert 'dark-plan-groups-shell' in html
    assert 'dark-table-heading' in html
    assert 'tw:bg-success/' not in html
    assert 'tw:bg-warning/' not in html
    assert 'tw:bg-info/' not in html
    assert 'tw:bg-error/' not in html


def test_advanced_fields_and_options_describe_user_visible_outcomes():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    expected_copy = (
        'Auto-gain coverage',
        'Fine · 1.5 dB',
        'Balanced · 3 dB · recommended',
        'Coarse · 6 dB',
        'If the temperature does not match',
        'Run pattern',
        'Combine captured images',
        'Reject outliers, then average · recommended',
        'Simple average',
        'Captured images per master set',
        'Longest exposure to include',
        'Exposure interval',
        'Exposure order',
        'Longest first · recommended',
        'Restore recommended capture groups',
        'Bad-pixel detection range',
        'Use image depth · automatic',
    )
    for copy in expected_copy:
        assert copy in html

    for obsolete_copy in (
        'Plan override',
        'Recapture recommended settings',
        'Rebuild this library',
        'Temperature use for this one run',
        'Gain spacing',
        'Source frames per master',
    ):
        assert obsolete_copy not in html


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


def test_primary_temperature_matching_and_advanced_series_are_separated():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    workflow = html.split('id="dark-temperature-workflow"', 1)[1].split(
        'id="dark-advanced-options"',
        1,
    )[0]
    advanced = html.split('id="dark-advanced-options"', 1)[1].split(
        'id="dark-run-instructions"',
        1,
    )[0]

    assert 'id="dark-temperature-range"' in workflow
    assert 'class="dark-builder-step-eyebrow">Step 1' in workflow
    assert 'Set temperature matching' in workflow
    assert 'These choices recalculate temperature coverage, the recommendation and the prepared capture plan throughout this page.' in workflow
    assert 'Allowed temperature difference' in workflow
    assert 'A larger value accepts temperatures farther away' in workflow
    assert 'saved for this camera only when a run starts' in workflow
    assert 'id="dark-temperature-range"' not in advanced
    assert 'id="dark-temperature-source"' in workflow
    assert 'Temperature sensor' in workflow
    assert 'id="dark-temperature-evaluation-summary"' in workflow
    assert 'id="dark-capture-mode"' not in workflow
    assert 'id="dark-temperature-policy"' not in workflow
    assert 'id="dark-temperature-delta"' not in workflow
    assert 'id="dark-temperature-target"' not in workflow
    assert 'The initial 5°C value is the legacy default' in html
    assert 'existing master temperatures do not change it' in html
    assert 'id="dark-capture-mode"' in advanced
    assert 'Capture once · standard' in advanced
    assert 'Repeat as temperature falls · advanced' in advanced
    assert 'id="dark-temperature-series-controls" class="tw:hidden' in advanced
    assert 'id="dark-temperature-delta"' in advanced
    assert 'Temperature drop between sets' in advanced
    assert 'separate from the allowed matching difference' in advanced
    assert 'id="dark-temperature-target"' in advanced
    assert 'Manual preparation required:' in advanced
    assert 'The builder cannot cover the camera or control the cooler.' in advanced
    assert 'id="dark-temperature-policy"' in advanced
    assert 'Capture a new dark and map · recommended' in advanced
    assert 'Use the existing dark and map' in advanced
    assert 'id="dark-strategy-control"' in advanced
    assert "$('#dark-temperature-series-controls').toggleClass('tw:hidden', !temperatureSeries);" in html
    assert "$('#dark-temperature-policy-control').toggleClass('tw:hidden', temperatureSeries);" in html
    assert "$('#dark-strategy-control').toggleClass('tw:hidden', temperatureSeries);" in html
    assert 'This change is not saved yet' in html

    temperature_position = html.index('id="dark-temperature-workflow"')
    recommendation_position = html.index('id="dark-recommendation-card"')
    explanation_position = html.index('id="dark-recommendation-explanation"')
    capture_position = html.index('id="dark-capture-controls"')
    advanced_position = html.index('id="dark-advanced-options"')
    assert temperature_position < recommendation_position
    assert recommendation_position < explanation_position
    assert explanation_position < capture_position
    assert capture_position < advanced_position


def test_temperature_guidance_explains_automatic_and_both_one_run_policies():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'Automatic uses the camera first.' in html
    assert 'Sensor names are never used to guess placement.' in html
    assert 'Automatic found no unique recent reading.' in html
    assert 'an existing dark and map at any temperature count as covered; only missing pairs are captured' in html
    assert 'Cooled profiles still use their target temperature.' in html
    assert 'Stored masters from ' in html


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
