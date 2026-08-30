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
    preview_strategy=None,
    automation_task_id=None,
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
        'strategy': preview_strategy or (
            action if action in ('complete', 'rebuild') else 'complete'
        ),
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
        'dark_automation_can_review': automation_can_run or config_requires_reload,
        'dark_automation_can_run': automation_can_run,
        'dark_config_requires_reload': config_requires_reload,
        'dark_automation_task_id': automation_task_id,
        'dark_library_can_manage': library_can_manage,
        'dark_library_task_active': False,
        'dark_library_catalog': library_catalog,
        'darkframe_list': darkframe_list,
        'bpm_list': bpm_list,
        'darkframe_summary': darkframe_summary,
        'bpm_summary': bpm_summary,
        'camera_name': 'Test Camera',
    })


def test_running_calibration_replaces_builder_with_dedicated_progress_page():
    html = _render_builder(
        'complete',
        stored_dark_count=1,
        stored_bpm_count=1,
        ready_count=1,
        suggested_count=4,
        automation_task_id=42,
    )

    assert 'id="dark-standard-page" class="tw:flex tw:flex-col tw:gap-4 tw:hidden"' in html
    assert 'id="dark-progress-panel" class="tw:card' in html
    progress_class = html.split('id="dark-progress-panel" class="', 1)[1].split('"', 1)[0]
    assert 'tw:hidden' not in progress_class
    assert 'function showDarkProgressPage()' in html
    assert "$('#dark-standard-page').addClass('tw:hidden');" in html
    assert 'showDarkProgressPage();' in html


def test_progress_page_lists_committed_master_details_and_returns_when_restored():
    html = _render_builder(
        'complete',
        stored_dark_count=1,
        stored_bpm_count=1,
        ready_count=1,
        suggested_count=4,
    )

    completed_table = html.split(
        'id="dark-progress-completed-section"',
        1,
    )[1].split('id="dark-progress-error"', 1)[0]
    for heading in ('Set', 'Profile', 'Gain', 'Exposure', 'Binning', 'Temperature', 'Source images'):
        assert f'<th>{heading}</th>' in completed_table
    assert 'Each row is a saved dark and matching map.' in completed_table
    assert 'function renderDarkCompletedMasterSets(details)' in html
    assert 'renderDarkCompletedMasterSets(status.completed_master_details);' in html
    assert 'id="dark-progress-capture-details"' in html
    assert 'id="dark-progress-removal-details" class="tw:hidden' in html
    assert 'Permanent library deletion' in html
    assert 'Records selected' in html
    assert 'Storage selected' in html
    assert "const removal = status.operation === 'flush';" in html
    assert ".toggleClass('tw:progress-error', removal)" in html
    assert "$('#dark-progress-bar').removeAttr('value');" in html
    assert "'Cancel deletion' : 'Cancel capture'" in html
    assert 'function scheduleDarkBuilderReturn(status)' in html
    assert "!['success', 'cancelled'].includes(status.status)" in html
    assert "darkReturnSection = status.status === 'success'" in html
    assert "darkReviewSection = status.status === 'review_required'" in html
    assert "let darkReviewSection = 'tab-darks';" in html
    assert "history.replaceState(null, '', '#' + darkReviewSection);" in html
    assert "history.replaceState(null, '', '#' + darkReturnSection);" in html
    assert 'window.location.reload();' in html

    actions_position = html.index('id="dark-progress-actions"')
    completed_position = html.index('id="dark-progress-completed-section"')
    assert actions_position < completed_position
    assert "const cancellationPending = status.status === 'cancel_requested';" in html
    assert ".prop('disabled', cancellationPending)" in html
    assert "$('#dark-cancel').prop('disabled', false);" in html
    assert 'Start dark capture' in html
    assert 'Temperature-series dark capture' in html
    assert 'Dark capture is running.' in html
    assert 'Cancel capture' in html
    assert 'Start dark calibration' not in html
    assert 'Cancel calibration' not in html


def test_builder_and_maintenance_are_separate_top_level_pages():
    html = _render_builder(
        'complete',
        stored_dark_count=2,
        stored_bpm_count=2,
        ready_count=1,
        suggested_count=4,
        library_can_manage=True,
    )

    for tab_id in (
            'dark-tab-darks',
            'dark-tab-bpm',
            'dark-tab-tool',
            'dark-tab-maintenance',
    ):
        assert f'id="{tab_id}"' in html
    assert 'dark-section-tabs dark-section-tabs--maintenance' in html
    assert 'id="dark-section-navigation" class="dark-section-navigation"' in html
    assert '.dark-section-navigation--enhanced.dark-section-navigation--hidden {' in html
    assert 'transform: translateY(calc(-100% - 1rem));' in html
    assert '@media (prefers-reduced-motion: reduce)' in html
    assert '.dark-section-navigation--enhanced .dark-section-tabs {' in html
    assert 'navigation.classList.add(\'dark-section-navigation--enhanced\');' in html
    assert 'function initializeDarkSectionNavigation() {' in html
    assert "scrollTarget.addEventListener('scroll', function() {" in html
    assert "overflowY === 'auto' || overflowY === 'scroll'" in html
    assert 'scrollContainer.scrollTop' in html
    assert 'window.requestAnimationFrame(updateNavigation)' in html
    assert 'navigation.offsetHeight + 24' in html
    assert "document.addEventListener('keydown', function() {" in html
    assert "document.addEventListener('pointerdown', function() {" in html
    assert 'keyboardInputActive = false;' in html
    assert 'dark-section-navigation--keyboard-focus' in html
    assert 'try {\n        initializeDarkSectionNavigation();' in html
    assert "console.warn('Scroll-aware dark-library navigation is unavailable.'" in html

    builder_page = html.split('<div id="tab-tool"', 1)[1].split(
        '<div id="tab-maintenance"',
        1,
    )[0]
    maintenance_page = html.split('<div id="tab-maintenance"', 1)[1].split(
        '<!-- Dark Frames Tab Panel -->',
        1,
    )[0]
    assert 'id="dark-advisor-body"' in builder_page
    assert 'id="dark-library-maintenance"' not in builder_page
    assert 'id="dark-library-maintenance"' in maintenance_page
    assert 'id="dark-library-selection-bar"' in maintenance_page
    assert html.count('id="dark-action-error"') == 1
    assert html.index('id="dark-action-error"') < html.index('id="tab-tool"')
    assert "if (darkLibraryCanManage) sections.push('tab-maintenance');" in html
    assert "if (['tab-tool', 'tab-maintenance'].includes(target))" in html


def test_dark_interface_visual_system_follows_semantic_theme_tokens():
    template = TEMPLATE_PATH.read_text(encoding='utf-8')

    assert '--dark-tool-radius: var(--radius-box' in template
    assert '--dark-structural: color-mix(in oklab, var(--color-base-content)' in template
    assert '--dark-structural-content: var(--color-base-content);' in template
    assert '--dark-success-content: var(--color-success-content);' in template
    assert '@supports (color: contrast-color(red))' in template
    assert '.dark-section-tab[aria-selected="true"]' in template
    assert 'background-color: var(--dark-structural-strong) !important;' in template
    assert '.dark-library-quick-filter--error' in template
    assert '--dark-filter-tone: var(--color-error);' in template
    assert '.dark-library-quick-filter--success' in template
    assert '.dark-library-quick-filter--warning' in template
    assert '.dark-library-quick-filter:nth-child' not in template
    assert '--dark-filter-tone: var(--color-success);' in template
    assert 'border-left: 0.25rem solid var(--dark-filter-tone) !important;' in template
    assert 'border-top: 0.25rem solid var(--dark-filter-tone) !important;' not in template
    coverage_accent_css = template.split('.dark-coverage-card::before {', 1)[1].split('}', 1)[0]
    assert 'top: 0;' in coverage_accent_css
    assert 'bottom: 0;' in coverage_accent_css
    assert 'left: 0;' in coverage_accent_css
    assert 'width: 0.22rem;' in coverage_accent_css
    assert 'right: 0;' not in coverage_accent_css
    assert 'height: 0.22rem;' not in coverage_accent_css
    assert '.dark-library-health-grid' in template
    assert 'grid-template-columns: repeat(6, minmax(0, 1fr));' in template
    assert '#dark-page-content .tw\\:alert-warning { border-left-color: var(--color-warning); }' in template
    assert '.dark-builder-step-marker--danger' in template
    assert 'dark_builder_preview_version' not in template
    assert '--dark-action-strong:' in template
    assert '--dark-warning-content: var(--color-warning-content);' in template
    assert '--dark-warning-outline:' in template
    assert '--dark-warning-surface:' not in template
    assert '--dark-warning-ink:' not in template
    assert '#dark-start:not(:disabled)' in template
    assert '#dark-start:disabled' in template
    assert 'class="dark-builder-back tw:btn tw:btn-sm tw:btn-neutral tw:btn-outline' in template
    assert 'tw:badge tw:badge-success tw:badge-outline tw:badge-sm" title="Image dimensions' in template
    assert 'dark-library-master-checkbox tw:checkbox tw:checkbox-sm' in template


@pytest.mark.parametrize(
    'action, stored_dark_count, stored_bpm_count, ready_count, suggested_count, title',
    (
        ('rebuild', 0, 0, 0, 17, 'Build or rebuild profiles'),
        ('complete', 20, 20, 5, 12, 'Add missing sets'),
        ('temperature', 20, 20, 17, 17, 'Add missing sets'),
        ('none', 20, 20, 17, 0, 'No library update needed'),
        ('rebuild', 20, 0, 0, 17, 'Build or rebuild profiles'),
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
    assert 'A master set is one dark plus its matching bad-pixel map' in html
    assert 'Before you start' not in html
    assert 'id="dark-recommendation-instructions"' not in html
    assert 'Cover the camera before starting' in html
    assert 'No light may reach the sensor.' in html
    assert 'The camera is fully covered' in html
    if not suggested_count:
        assert 'Nothing to do.' in html
    assert 'Guided capture' in html
    assert 'Preview 2026.08.23.12' not in html
    assert 'lengthens exposure first, then changes gain at maximum exposure' in html
    assert 'masters from 15.0°C to 25.0°C match' in html
    assert 'Each set is checked separately, and existing layers stay stored.' in html
    assert 'Each master set uses this many images to build one dark and one bad-pixel map.' in html
    assert 'Step down from the longest exposure by this amount' in html
    if suggested_count:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4"' in html
    else:
        assert 'id="dark-run-instructions" class="tw:flex tw:flex-col tw:gap-4 tw:hidden"' in html


@pytest.mark.parametrize(
    'action, ready_count, suggested_count, title, recommended_option',
    (
        ('complete', 5, 12, 'Add missing sets', 'dark-completion-option'),
        ('temperature', 17, 17, 'Add missing sets', 'dark-completion-option'),
        ('rebuild', 0, 17, 'Build or rebuild profiles', 'dark-rebuild-option'),
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
    update_choices = html.split('Update options', 1)[1].split(
        'id="dark-planning-warnings"',
        1,
    )[0]

    title_markup = recommendation.split('id="dark-recommendation-title"', 1)[1].split(
        '</h5>',
        1,
    )[0]
    strategy_options = html.split('id="dark-strategy"', 1)[1].split('</select>', 1)[0]
    assert title in title_markup
    expected_state = 'dark-recommendation-state-success' \
        if action == 'none' else 'dark-recommendation-state-warning'
    assert expected_state in recommendation
    assert 'dark-recommendation-state-info' not in recommendation
    expected_badge = 'tw:badge-success' if action == 'none' else 'tw:badge-warning'
    assert expected_badge in recommendation
    if recommended_option:
        assert f'id="{recommended_option}-badge"' in update_choices
        assert f'{title} · recommended</option>' in strategy_options
    else:
        assert ' · recommended</option>' not in strategy_options
    assert 'marks the builder’s choice' in update_choices
    assert 'the border marks your current choice' in update_choices


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
    assert html.count('<strong>Matches setup</strong> checks image size, binning and bit depth') == 2
    assert html.count('Select a card to filter the table.') == 2
    assert html.count('>Quick filters</span>') == 2
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
    assert html.count('inactive entries stay stored') == 2

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
    assert 'grid-template-columns: repeat(6, minmax(0, 1fr));' in html
    assert "const darkLibraryFilterColumns = {" in html
    assert 'active: 2' in html
    assert 'partner: 3' in html
    assert 'compatible: 4' in html
    assert 'file: 12' in html
    assert html.count("order: [[1, 'desc']]") == 2
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

    assert '5 of 17 recommended sets match across all temperatures; 0 match here.' in html
    assert 'The plan adds the 17 missing sets and keeps every stored master.' in html
    assert '5 of 17 sets covered across all temperatures' in html
    assert '0 of 17 ready at the cooler target (Config → Camera) or current temperature' in html


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
    assert 'Output and target temperature' in html
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
                'active_selection': {'dark_ids': [1], 'bpm_ids': [11]},
                'inactive_selection': {'dark_ids': [2], 'bpm_ids': [12]},
                'activatable_selection': {'dark_ids': [2], 'bpm_ids': [12]},
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
                    'active_selection': {'dark_ids': [1], 'bpm_ids': [11]},
                    'inactive_selection': {'dark_ids': [2], 'bpm_ids': [12]},
                    'activatable_selection': {'dark_ids': [2], 'bpm_ids': [12]},
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
                        'active_selection': {'dark_ids': [1], 'bpm_ids': [11]},
                        'inactive_selection': {'dark_ids': [2], 'bpm_ids': [12]},
                        'activatable_selection': {'dark_ids': [2], 'bpm_ids': [12]},
                    'master_sets': [{
                        'gain': 10,
                        'exposure': 30,
                        'temperature': 43.2,
                        'paired': True,
                        'status': 'active',
                            'size': '2.0 KiB',
                            'selection': {'dark_ids': [1], 'bpm_ids': [11]},
                            'active_selection': {'dark_ids': [1], 'bpm_ids': [11]},
                            'inactive_selection': {'dark_ids': [], 'bpm_ids': []},
                            'activatable_selection': {'dark_ids': [], 'bpm_ids': []},
                    }, {
                        'gain': 20,
                        'exposure': 30,
                        'temperature': 42.1,
                        'paired': True,
                        'status': 'inactive',
                            'size': '2.0 KiB',
                            'selection': {'dark_ids': [2], 'bpm_ids': [12]},
                            'active_selection': {'dark_ids': [], 'bpm_ids': []},
                            'inactive_selection': {'dark_ids': [2], 'bpm_ids': [12]},
                            'activatable_selection': {'dark_ids': [2], 'bpm_ids': [12]},
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

    assert 'temperature groups ±5°C' in html
    assert '42.1 to 43.2°C' in html
    assert '2 master sets' in html
    assert '>1 active · 1 inactive</span>' in html
    assert '>Active</span>' in html
    assert '>Inactive</span>' in html
    assert "'Delete ' + scopeKind.toLowerCase()" in html

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
    assert 'dark-builder-step-marker dark-builder-step-marker--danger' not in maintenance
    assert 'class="dark-builder-step-marker"' not in maintenance
    assert 'Library tools' in maintenance
    assert 'dark-library-maintenance-body' in maintenance
    assert '<section id="dark-library-maintenance"' in html
    assert '<details id="dark-library-maintenance"' not in html
    assert 'class="dark-library-maintenance-header"' in html
    assert 'class="dark-library-maintenance-body tw:collapse-content' not in html
    assert 'Stored darks and maps' in maintenance
    assert 'Camera libraries' in maintenance
    assert 'Storage used' in maintenance
    assert maintenance.count('dark-library-storage-summary-cell') == 3
    assert 'dark-library-safety-note' in maintenance
    assert 'Browse or combine.' in maintenance
    assert 'Tick items at any level to combine them' in maintenance
    assert 'dark-library-browser-grid' in maintenance
    assert maintenance.count('<section class="dark-library-browser-column"') == 3
    assert 'data-camera-option="1"' in maintenance
    assert 'data-profile-option="1-0"' in maintenance
    assert 'data-layer-option="1-0-0"' in maintenance
    assert 'data-master-panel="1-0-0"' in maintenance
    assert 'dark-library-camera-list' not in maintenance
    assert 'dark-library-cleanup' not in maintenance
    assert '<details class="dark-library-camera' not in maintenance
    assert '<details class="dark-library-profile' not in maintenance
    assert 'Activate all inactive' in maintenance
    assert 'Deactivate all active' in maintenance
    assert 'Delete all inactive' in maintenance
    assert 'id="dark-library-scope-activate"' in maintenance
    assert 'id="dark-library-scope-deactivate"' in maintenance
    assert 'id="dark-library-scope-delete-inactive"' in maintenance
    assert 'id="dark-library-scope-delete"' in maintenance
    assert 'Actions apply to · <span id="dark-library-current-scope-kind">' in maintenance
    assert maintenance.count('dark-library-action-scope-badge') == 3
    assert maintenance.count('dark-library-table-scope-badge') == 1
    assert 'Listed below · Temperature group' in maintenance
    assert 'files from this temperature group only' in maintenance
    assert "removeClass('is-action-scope')" in html
    assert "addClass('is-action-scope')" in html
    assert maintenance.count('dark-library-scope-checkbox') == 3
    assert maintenance.count('dark-library-master-checkbox') == 2
    assert maintenance.count('dark-library-selection-checkbox') == 5
    assert 'dark-library-master-table' in maintenance
    assert '<th>Master set</th><th>Status</th><th>Size</th><th>Actions</th>' in maintenance
    assert 'id="dark-library-selection-bar"' in maintenance
    assert 'id="dark-library-selection-camera"' in maintenance
    assert 'id="dark-library-selection-summary"' in maintenance
    assert 'id="dark-library-clear-selection"' in maintenance
    assert 'id="dark-library-deactivate-selected"' in maintenance
    assert 'id="dark-library-activate-selected"' in maintenance
    assert 'id="dark-library-delete-selected"' in maintenance
    assert 'Deactivate selected' in maintenance
    assert 'Delete selected' in maintenance
    assert 'Overlapping items are counted once.' in maintenance
    assert '--dark-readable-' not in html
    assert '--dark-tool-radius: var(--radius-box' in html
    assert '--dark-success-text:' in html
    assert '--dark-success-outline:' in html
    assert '--dark-success-content: var(--color-success-content);' in html
    assert '#dark-page-content .tw\\:alert {' in html
    assert 'border-left-width: 0.25rem;' in html
    assert html.count('class="dark-progress-fact-grid') == 3
    assert '.dt-paging-button.current' in html
    assert 'background-color: var(--dark-structural-strong) !important;' in html
    assert html.count('dark-library-quick-filter--success') >= 4
    assert html.count('dark-library-quick-filter--warning') >= 4
    assert html.count('dark-library-quick-filter--error') >= 2
    assert 'Activate selected' in maintenance
    assert 'id="dark-library-selection-guidance"' in maintenance
    assert 'function setDarkSelectionConfirmationOpen(open)' in html
    assert 'darkSelectionConfirmationOpen || !hasSelection' in html
    assert 'setDarkSelectionConfirmationOpen(true);' in html
    assert 'setDarkSelectionConfirmationOpen(false);' in html
    assert 'preview.unchanged_entry_count' in html
    assert 'id="dark-library-confirmation-modal" class="tw:modal"' in maintenance
    assert 'darkLibraryConfirmationModal.addEventListener(\'close\'' in html
    assert 'darkLibraryConfirmationModal.addEventListener(\'keydown\'' in html
    assert "event.key !== 'Escape'" in html
    assert "showDarkLibraryConfirmation('eligibility', button[0]);" in html
    assert "showDarkLibraryConfirmation('removal', button[0]);" in html
    assert "document.getElementById('dark-eligibility-confirmation').scrollIntoView" not in html
    assert "document.getElementById('dark-removal-confirmation').scrollIntoView" not in html
    assert 'id="dark-eligibility-confirmation"' in maintenance
    assert 'Deactivation keeps the files and can be reversed.' in maintenance

    assert '.dark-library-browser-grid {' in html
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr));' in html
    assert 'max-height: clamp(9rem, 28vh, 14rem);' in html
    assert 'scrollbar-gutter: stable;' in html
    assert '.dark-library-browser-list.tw\\:hidden {' in html
    assert '@container dark-library-browser-column (max-width: 24rem)' in html
    assert html.count('if (list[0]) list[0].scrollTop = 0;') == 2
    assert '#dark-library-maintenance > .dark-library-maintenance-body' in html
    maintenance_style = html.split('#dark-library-maintenance {', 1)[1].split('}', 1)[0]
    assert 'border-left' not in maintenance_style
    assert 'background-color: var(--color-base-200);' in html
    assert 'background-color: color-mix(in oklab, var(--color-warning) 12%, var(--color-base-100));' in html
    assert 'id="dark-removal-confirmation-input" class="tw:input tw:input-bordered tw:input-error' in html
    assert 'Type <span class="tw:font-mono">DELETE</span> to confirm permanent deletion' in html
    assert "const darkRemovalConfirmationText = 'DELETE';" in html
    assert "confirmation !== darkRemovalConfirmationText" in html
    assert 'dark-removal-camera-name' not in html
    assert 'Enter the camera name exactly' not in html
    assert '.dark-library-selection-bar {' in html
    assert 'position: fixed;' in html
    assert 'bottom: max(0.75rem, env(safe-area-inset-bottom));' in html
    assert '#dark-page-content.dark-library-selection-mode' in html
    assert 'function scheduleDarkSelectionBarLayout()' in html
    assert "'--dark-library-selection-center'" in html
    assert "'--dark-library-selection-height'" in html
    assert "document.getElementById('dark-library-maintenance') || page" in html
    selection_actions_css = html.split('.dark-library-selection-actions {', 1)[1].split(
        '/* Library overview and tables */',
        1,
    )[0]
    assert 'grid-template-columns: repeat(4, minmax(8rem, 1fr));' in selection_actions_css
    assert '@container (max-width: 64rem)' in selection_actions_css
    assert '@container (max-width: 42rem)' in selection_actions_css
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in selection_actions_css
    assert '@media (max-width: 479px)' in selection_actions_css
    assert 'function keepDarkSelectionRowVisible(checkbox)' in html
    assert 'function initializeDarkLibraryBrowser()' in html
    assert 'initializeDarkSelectionBarLayout();' in html
    assert 'initializeDarkLibraryBrowser();' in html
    assert 'function updateDarkMarkedSelection()' in html
    assert 'function darkSelectionBatchesFromElements(elements, attributeName)' in html
    assert 'function darkButtonSelectionBatches(button)' in html
    assert "selected.length + ' item'" in html
    assert "data-kind=\"camera library\"" in maintenance
    assert "data-kind=\"image profile\"" in maintenance
    assert "data-kind=\"temperature group\"" in maintenance
    assert "data-kind=\"master set\"" in maintenance
    assert "toolbar.toggleClass('tw:hidden', !hasSelection || darkSelectionConfirmationOpen);" in html
    assert 'function renderDarkCoverageImpact(selector, impact, fallbackMessage)' in html
    assert 'selections: pendingDarkEligibility.selections' in html
    assert 'selections: pendingDarkRemoval.selections' in html
    assert "if (darkLibraryCanManage) {" in html

    assert 'grid-template-columns: repeat(6, minmax(0, 1fr));' in html
    assert '@media (max-width: 959px)' in html
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr));' in html
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in html
    assert '@media (max-width: 399px)' in html
    health_grid_css = html.split('.dark-library-health-grid {', 1)[1].split(
        '.dark-library-quick-filter',
        1,
    )[0]
    assert 'repeat(auto-fit' not in health_grid_css


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

    assert 'An administrator can run this plan for a local camera.' in html
    assert 'Library maintenance' not in html
    assert 'id="dark-tab-maintenance"' not in html
    assert 'id="tab-maintenance"' not in html
    assert 'const darkAutomationCanRun = false;' in html
    assert 'const darkAutomationCanReview = false;' in html
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
    assert '>Add missing sets · recommended</option>' in html
    assert '>Replace recommended sets</option>' in html
    assert '>Build or rebuild profiles</option>' in html
    assert '>Edit the plan manually</option>' in html
    assert (
        "complete: 'Capture only missing sets. Stored masters do not change.'"
    ) in html
    assert 'Each new pair becomes active and deactivates its older equivalent.' in html
    assert 'Extra sets in the selected profiles and temperature range become inactive.' in html
    assert 'Choose rows, gains and exposures under Step 3 → Advanced options.' in html
    assert 'Step 3 → Advanced options → Library update' in html
    assert 'id="dark-completion-option" class="dark-update-option dark-update-option--selected' in html
    assert 'id="dark-completion-option-badge" class="tw:badge tw:badge-primary tw:badge-sm">Recommended' in html
    assert 'Replace recommended sets</strong> and <strong>Build or rebuild profiles</strong> both capture 17 master sets' in html
    assert 'Replace changes only recommended equivalents' in html
    assert 'Build or rebuild also deactivates older extras' in html
    assert 'Inactive masters stay stored but are ignored.' in html
    assert 'Completed sets are kept; the current partial set is discarded.' in html
    assert "$('#dark-cancel-safety').toggleClass('tw:hidden', terminal);" in html


@pytest.mark.parametrize(
    'strategy, selected_option',
    (
        ('complete', 'dark-completion-option'),
        ('refresh', 'dark-refresh-option'),
        ('rebuild', 'dark-rebuild-option'),
        ('custom', 'dark-custom-option'),
    ),
)
def test_library_update_highlight_follows_the_selected_strategy(
    strategy,
    selected_option,
):
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
        preview_strategy=strategy,
    )
    choices = html.split('Update options', 1)[1].split(
        'id="dark-planning-warnings"',
        1,
    )[0]

    assert choices.count('dark-update-option--selected') == 1
    assert f'id="{selected_option}" class="dark-update-option dark-update-option--selected' in choices
    assert 'id="dark-completion-option-badge" class="tw:badge tw:badge-primary tw:badge-sm">Recommended' in choices
    assert "$('.dark-update-option').removeClass('dark-update-option--selected');" in html
    assert "if (selectedOption) $(selectedOption).addClass('dark-update-option--selected');" in html
    capture_mode_controls = html.split('function updateDarkCaptureModeControls()', 1)[1].split(
        'function setDarkPlanRefreshing',
        1,
    )[0]
    assert 'updateDarkUpdateChoiceHighlight();' in capture_mode_controls


def test_how_decided_marks_every_advanced_plan_deviation_as_customized():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )
    explanation = html.split('id="dark-recommendation-explanation"', 1)[1].split(
        'id="dark-capture-controls"',
        1,
    )[0]

    assert 'id="dark-customized-plan-note"' in explanation
    assert 'Customized capture plan' in explanation
    assert 'You changed the prepared plan.' in explanation
    assert 'badges still show the builder’s choices' in explanation
    assert 'function resolveDarkPreparedPlanCustomization(state)' in html
    assert "selected_strategy: $('#dark-strategy').val()" in html
    assert 'plan_inputs_changed: planInputsChanged' in html
    assert 'capture_groups_changed: darkCaptureGroupsEdited' in html
    assert "capture_mode_changed: $('#dark-capture-mode').val() !== 'single'" in html
    assert "stacking_method_changed: $('#dark-method').val() !== recommendedMethod" in html
    assert "frame_count_changed: Number($('#dark-frame-count').val()) !== initialFrameCount" in html
    assert "capture_order_changed: $('#dark-capture-order').val() !== initialCaptureOrder" in html
    assert "$('#dark-customized-plan-note').toggleClass(" in html


def test_recommendation_origin_and_overviews_are_explicitly_labelled():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'How the recommended grid is built' in html
    assert 'The builder reads the saved day, night, moon and SQM profiles from Config → Camera.' in html
    assert 'Inputs used' in html
    assert 'Camera settings · Config → Camera' in html
    assert 'id="dark-saved-exposure-max">30 seconds</strong> (capped by the camera if necessary)' in html
    assert 'Strategy: <strong>Exposure priority</strong>' in html
    assert 'Builder settings' in html
    assert 'id="dark-input-temperature-source">Automatic</strong>' in html
    assert 'id="dark-input-temperature-range">5</span>°C' in html
    assert 'id="dark-input-exposure-step">5</span> seconds' in html
    assert 'Step 1 supplies temperature settings; Step 3 → Advanced options supplies the interval' in html
    assert 'Where the inputs come from' not in html
    assert 'Camera-reported limits' not in html
    assert '1 second is always included' in html
    assert 'duplicate combinations count once' in html
    assert 'id="dark-recommendation-target-count">17</span> recommended master' in html
    assert 'A stored set may fall outside today’s recommendation after Config → Camera settings change.' in html
    assert 'It is not damaged' in html
    assert 'Plan overview' in html
    assert 'Generated from the connected camera, Config → Camera, and Steps 1 and 3.' in html
    assert 'id="dark-recommendation-step-title" class="dark-builder-step-title">Review the recommendation' in html
    assert 'Recommended update' in html
    assert 'Capture the plan' in html
    assert 'Use the prepared plan, or open Advanced options below.' in html
    assert 'Defaults come from Config → Camera.' in html
    assert 'Normally keep the Config → Camera maximum or camera limit.' in html
    assert 'Each row is a day, night, moon or SQM profile from Config → Camera.' in html


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

    assert html.count('class="dark-builder-step dark-builder-panel') == 3
    assert 'id="dark-builder-steps" class="tw:steps tw:steps-horizontal tw:w-full"' in html
    assert html.count('data-dark-builder-step-indicator="') == 3
    assert 'data-dark-builder-go="1"' in html
    assert 'data-dark-builder-go="2"' in html
    assert 'data-dark-builder-go="3"' in html
    assert html.count('dark-builder-step-header') >= 4
    maintenance = html.split('id="dark-library-maintenance"', 1)[1].split(
        '<!-- Dark Frames Tab Panel -->',
        1,
    )[0]
    assert 'class="dark-builder-step-marker"' not in maintenance
    assert 'dark-builder-step-marker--danger' not in maintenance
    assert 'class="dark-builder-step-eyebrow">Step 1' in html
    assert 'class="dark-builder-step-eyebrow">Step 2' in html
    assert 'class="dark-builder-step-eyebrow">Step 3' in html
    assert 'Choose temperature matching' in html
    assert 'Review the recommendation' in html
    assert 'Capture the plan' in html

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
    assert 'dark-recommendation-state-info' not in html
    assert 'dark-coverage-card--success' in html
    assert html.count('dark-coverage-card--success') >= 2
    assert 'dark-coverage-card--info' not in html
    assert 'dark-coverage-card--warning' in html
    assert 'dark-coverage-card--error' in html
    assert 'dark-library-storage-summary' in html
    assert 'dark-plan-groups-shell' in html
    assert 'dark-table-heading' in html
    assert 'function showDarkBuilderStep(step, options)' in html
    assert ".toggleClass('tw:hidden', !active).attr('aria-hidden'" in html
    assert "temperatureRange.reportValidity();" in html
    assert ".attr('data-content', complete ? '✓' : String(indicatorStep));" in html
    assert '.dark-builder-step::before {\n    display: none;' in html
    assert '.dark-builder-panel.tw\\:hidden {\n    display: none !important;' in html
    assert 'border-left-width: 1px;' in html
    assert 'tw:bg-success/' not in html
    assert 'tw:bg-warning/' not in html
    assert 'tw:bg-info/' not in html
    assert 'tw:bg-error/' not in html


def test_disabled_action_buttons_remain_visibly_distinct_in_every_theme():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert '#dark-page-content .tw\\:btn:disabled' in html
    assert '#dark-page-content .tw\\:btn[aria-disabled="true"]' in html
    assert 'color-mix(in oklab, var(--color-base-content) 48%, transparent)' in html
    assert 'color-mix(in oklab, var(--color-base-content) 6%, var(--color-base-200))' in html
    assert 'cursor: not-allowed !important;' in html


def test_advanced_fields_and_options_describe_user_visible_outcomes():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    expected_copy = (
        'Auto-gain spacing',
        'Fine · 1.5 dB',
        'Balanced · 3 dB · recommended',
        'Coarse · 6 dB',
        'If no master matches the temperature',
        'Run pattern',
        'Combine source images',
        'Average after removing outliers · recommended',
        'Average all images',
        'Images per master set',
        'Longest exposure to include',
        'Exposure interval',
        'Exposure order',
        'Longest first · recommended',
        'Restore recommended groups',
        'Bad-pixel threshold range',
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


def test_every_capture_group_edit_switches_to_manual_and_can_restore_its_base_strategy():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert "let darkCaptureGroupBaseStrategy = darkSingleStrategy;" in html
    assert ".on('change input', function() { syncDarkCaptureGroupStrategy(true); });" in html
    assert "function resolveDarkCapturePlanStrategy(" in html
    assert "strategyControl.val(resolveDarkCapturePlanStrategy(" in html
    assert "darkCapturePlanInputSignature(readDarkCapturePlanInputState())" in html
    assert "$('#dark-exposure-max, #dark-exposure-step').on('input', function()" in html
    assert "syncDarkCaptureGroupStrategy(true);" in html
    assert "$('#dark-refresh-plan').on('click', restoreDarkRecommendedCaptureGroups);" in html
    assert "preserve_group_edits: true" in html


def test_advanced_plan_validation_blocks_invalid_capture_requests():
    html = _render_builder(
        'complete',
        stored_dark_count=20,
        stored_bpm_count=20,
        ready_count=5,
        suggested_count=12,
    )

    assert 'id="dark-plan-validation"' in html
    assert 'Fix the plan' in html
    assert 'Choose 3 to 50 images per master set.' in html
    assert 'A selected gain is below the camera minimum.' in html
    assert 'Exposure must be greater than zero.' in html
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
    assert 'Choose temperature matching' in workflow
    assert 'The page updates immediately.' in workflow
    assert 'Allowed temperature difference' in workflow
    assert 'A larger range needs fewer new temperature layers.' in workflow
    assert 'saved for this camera when capture starts' in workflow
    assert 'id="dark-temperature-range"' not in advanced
    assert 'id="dark-temperature-source"' in workflow
    assert 'Temperature sensor' in workflow
    assert 'id="dark-temperature-evaluation-summary"' in workflow
    assert 'id="dark-capture-mode"' not in workflow
    assert 'id="dark-temperature-policy"' not in workflow
    assert 'id="dark-temperature-delta"' not in workflow
    assert 'id="dark-temperature-target"' not in workflow
    assert '5°C is the default' in html
    assert 'It does not control cooling.' in html
    assert 'id="dark-capture-mode"' in advanced
    assert 'Capture plan once · standard' in advanced
    assert 'Repeat as temperature falls · advanced' in advanced
    assert 'id="dark-temperature-series-controls" class="tw:hidden' in advanced
    assert 'id="dark-temperature-delta"' in advanced
    assert 'Temperature drop between sets' in advanced
    assert 'separate from the allowed temperature difference' in advanced
    assert 'id="dark-temperature-target"' in advanced
    assert 'Prepare this manually:' in advanced
    assert 'The builder cannot cover or cool the camera.' in advanced
    assert 'id="dark-temperature-policy"' in advanced
    assert 'Capture a matching dark and map · recommended' in advanced
    assert 'Reuse a pair at any temperature' in advanced
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

    assert 'Automatic prefers the camera sensor.' in html
    assert 'one unambiguous source from Config → Sensors' in html
    assert 'never guesses from its name.' in html
    assert 'Automatic found no unique recent reading.' in html
    assert 'any stored temperature counts' in html
    assert 'Cooled profiles still use targets from Config → Camera.' in html
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

    assert 'The saved settings are newer than those used by the capture service.' in html
    assert 'Steps 1 and 2 remain available for review; reload the service before capture.' in html
    assert 'const darkAutomationCanReview = true;' in html
    assert 'const darkAutomationCanRun = false;' in html
    assert 'id="dark-temperature-workflow"' in html
    assert 'id="dark-temperature-source"' in html
    assert 'id="dark-temperature-range"' in html
    assert 'class="dark-builder-step-eyebrow">Step 2' in html
    assert 'Step 1 of 2' in html
    assert 'Step 2 of 2' in html
    assert 'data-dark-builder-step-indicator="1"' in html
    assert 'data-dark-builder-step-indicator="2"' in html
    assert 'data-dark-builder-step-indicator="3"' not in html
    assert 'data-dark-builder-go="3"' not in html
    assert 'id="dark-capture-controls" class="dark-builder-step dark-builder-panel tw:hidden"' in html
    assert 'id="dark-start"' in html
    assert 'if (darkAutomationCanReview) {' in html
