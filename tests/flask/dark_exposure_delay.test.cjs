const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(__dirname, '../../indi_allsky/flask/templates/darks.html'), 'utf8');

function builder(delay, mode = 'single', delayMode = 'fixed') {
    const values = {
        '#dark-frame-count': '3', '#dark-exposure-delay': delay,
        '#dark-exposure-delay-mode': delayMode,
        '#dark-exposure-max': '5', '#dark-exposure-step': '1',
        '#dark-temperature-range': '5', '#dark-capture-mode': mode,
        '#dark-temperature-delta': '5', '#dark-temperature-target': '8',
        '#dark-strategy': 'custom',
        '.dark-group-gains': '0, 100', '.dark-group-exposures': '1, 5',
        '.dark-group-binning': '1',
    };
    const output = {};
    const requests = [];
    function $(selector) {
        if (typeof selector === 'object') return selector;
        const field = {
            0: {checkValidity: () => true},
            val: () => values[selector],
            text: value => { output[selector] = value; return field; },
            find: $, is: () => true, data: () => 'test',
            each: callback => callback.call({find: $, data: () => 'test'}),
            prop: (name, value) => { output[selector + ':' + name] = value; return field; },
            toggleClass: (name, value) => { output[selector + ':' + name] = value; return field; },
            addClass: () => field, removeClass: () => field,
        };
        return field;
    }
    const context = vm.createContext({
        $, currentDarkPlan: {groups: [], temperature_set_count: 4},
        parseDarkNumberList: text => text.split(',').map(Number),
        darkFormatDuration: seconds => String(seconds),
        darkFormatBytes: bytes => String(bytes),
        updateDarkPreparedPlanCustomizationNote() {}, updateDarkStartButton() {},
        darkPlanRefreshTimer: null, darkPlanRequestRevision: 0,
        darkCaptureGroupsEdited: false, darkCaptureGroupBaseStrategy: 'custom',
        camera_id: 1, darkPlanUrl: '/plan', darkStartUrl: '/start',
        showDarkActionError() {}, setDarkPlanRefreshing() {}, updateDarkOptionGuidance() {},
        darkOptionalNumber: () => 8, collectDarkGroups: () => [],
        renderDarkPlan() {}, showDarkProgressPage() {}, renderDarkProgress() {}, scheduleDarkPoll() {},
        darkJsonRequest: async (url, options) => {
            requests.push({url, data: JSON.parse(options.body)});
            return {task_id: 1};
        },
    });
    for (const name of ['darkExposureDelayValue', 'updateDarkExposureDelayControls',
        'darkPlanValidationFailure', 'resolveDarkPreparedPlanCustomization',
        'updateDarkPlanSummary', 'refreshDarkPlan', 'startDarkCalibration']) {
        const source = template.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
        assert.ok(source, `Missing builder function ${name}`);
        vm.runInContext(source[0], context);
    }
    context.updateDarkPlanValidation = () => context.darkPlanValidationFailure(undefined, false) === null;
    return {context, output, requests, values};
}

test('zero and fractional delays are valid; blank, negative and nonfinite delays are blocked', () => {
    for (const value of ['0', '2.5', '60']) {
        assert.equal(builder(value).context.darkPlanValidationFailure(undefined, false), null);
    }
    for (const value of ['', ' ', '-1', 'NaN', 'Infinity']) {
        assert.match(builder(value).context.darkPlanValidationFailure(undefined, false).message, /0 or more seconds/);
    }
});

test('summary includes cooldown for every master and temperature set', () => {
    for (const [mode, multiplier] of [['single', 1], ['temperature_series', 4]]) {
        const baseline = builder('0', mode);
        const delayed = builder('2.5', mode);
        baseline.context.updateDarkPlanSummary();
        delayed.context.updateDarkPlanSummary();
        // Two gains x two exposures x two gaps x 2.5s; processing covers the final cooldown.
        assert.equal(Number(delayed.output['#dark-primary-time']) - Number(baseline.output['#dark-primary-time']), 20 * multiplier);
        assert.equal(delayed.output['#dark-primary-targets'], baseline.output['#dark-primary-targets']);
    }
});

test('preview and start send the chosen delay without changing it', async () => {
    for (const value of ['0', '2.5']) {
        const {context, requests} = builder(value);
        await context.refreshDarkPlan({preserve_group_edits: true});
        await context.startDarkCalibration();
        assert.deepEqual(requests.map(request => request.url), ['/plan', '/start']);
        assert.ok(requests.every(request => request.data.exposure_delay === Number(value)));
    }
});

test('invalid delay prevents preview and capture requests', async () => {
    const {context, requests} = builder('-1');
    await context.refreshDarkPlan();
    await context.startDarkCalibration();
    assert.equal(requests.length, 0);
});

test('changing only the delay marks a prepared plan as customized', () => {
    const {context} = builder('2.5');
    assert.equal(context.resolveDarkPreparedPlanCustomization({exposure_delay_changed: true}), true);
});

test('automatic mode ignores fixed seconds and sends the matching-exposure choice', async () => {
    for (const value of ['0', '2.5', '', '-1']) {
        const {context, requests} = builder(value, 'single', 'exposure');
        assert.equal(context.darkPlanValidationFailure(undefined, false), null);
        await context.refreshDarkPlan({preserve_group_edits: true});
        await context.startDarkCalibration();
        assert.deepEqual(requests.map(request => request.url), ['/plan', '/start']);
        assert.ok(requests.every(request => request.data.exposure_delay === 'exposure'));
    }
});

test('automatic estimates follow the exposure list and temperature repetitions', () => {
    for (const [mode, multiplier] of [['single', 1], ['temperature_series', 4]]) {
        const baseline = builder('0', mode);
        const automatic = builder('100', mode, 'exposure');
        baseline.context.updateDarkPlanSummary();
        automatic.context.updateDarkPlanSummary();
        // Two gains x two gaps x (1s + 5s); processing covers each final cooldown.
        assert.equal(Number(automatic.output['#dark-primary-time']) - Number(baseline.output['#dark-primary-time']), 24 * multiplier);
    }
});

test('cooldowns longer than processing add only their remaining time at set boundaries', () => {
    for (const [mode, multiplier] of [['single', 1], ['temperature_series', 4]]) {
        const fixed = builder('60', mode);
        fixed.context.updateDarkPlanSummary();
        // Four masters: 36s total exposure + four sets of (2 x 60s gaps + max(30s, 60s)).
        assert.equal(Number(fixed.output['#dark-primary-time']), 756 * multiplier);
        const automatic = builder('0', mode, 'exposure');
        automatic.values['.dark-group-exposures'] = '60';
        automatic.context.updateDarkPlanSummary();
        assert.equal(Number(automatic.output['#dark-primary-time']), 720 * multiplier);
    }
});

test('switching modes hides fixed seconds and preserves the entered value', () => {
    const {context, values, output} = builder('2.5');
    values['#dark-exposure-delay-mode'] = 'exposure';
    context.updateDarkExposureDelayControls();
    assert.equal(context.darkExposureDelayValue(), 'exposure');
    assert.equal(output['#dark-exposure-delay:disabled'], true);
    assert.equal(output['#dark-exposure-delay-seconds:tw:hidden'], true);
    values['#dark-exposure-delay-mode'] = 'fixed';
    context.updateDarkExposureDelayControls();
    assert.equal(context.darkExposureDelayValue(), 2.5);
    assert.equal(output['#dark-exposure-delay:disabled'], false);
    assert.equal(output['#dark-exposure-delay-seconds:tw:hidden'], false);
});
