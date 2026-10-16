// Exercise the real polling/rendering functions with deterministic worker states.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const template = fs.readFileSync(path.join(
    __dirname, '../../../indi_allsky/flask/templates/asi676mc_calibration.html'
), 'utf8');

function functionSource(name) {
    const start = template.search(new RegExp(`(?:async )?function ${name}\\(`));
    assert.notEqual(start, -1, `Missing function ${name}`);
    const end = template.indexOf('\n}', start);
    assert.notEqual(end, -1);
    return template.slice(start, end + 2);
}

async function run(states) {
    const elements = new Map();
    const snapshots = [];
    const element = (selector) => {
        if (!elements.has(selector)) elements.set(selector, {visible: false});
        return elements.get(selector);
    };
    const $ = (selector) => {
        const targets = selector.split(',').map(value => element(value.trim()));
        const apply = (key, value) => {
            targets.forEach(target => { target[key] = value; });
            return api;
        };
        const api = {
            text: value => apply('text', value),
            css: (key, value) => apply(key, value),
            attr: (key, value) => apply(key, value),
            prop: (key, value) => apply(key, value),
            show: () => apply('visible', true),
            hide: () => apply('visible', false),
            toggle: value => apply('visible', Boolean(value)),
            removeClass: () => api,
            addClass: () => api,
        };
        return api;
    };
    const context = vm.createContext({
        $, activeCalibrationSourceKind: null,
        showCalibrationProgressView() {},
        renderCalibrationResult() {},
        rememberCalibrationSession() {},
        calibrationReportUrlTemplate: '/report/SESSION_ID',
        calibrationUrl: (url, id) => url.replace('SESSION_ID', id),
        setTimeout: callback => callback(),
        fetchCalibrationStatus: async () => {
            assert.ok(states.length, 'Polling exceeded supplied worker states');
            return states.shift();
        },
    });
    for (const name of ['setCalibrationProgress', 'showCalibrationFailure', 'pollCalibration']) {
        vm.runInContext(functionSource(name), context);
    }
    const renderProgress = context.setCalibrationProgress;
    context.setCalibrationProgress = (...args) => {
        renderProgress(...args);
        snapshots.push({
            percent: element('#calibration-progress').text,
            explanation: element('#calibration-progress-explanation').visible,
            stage: element('#calibration-stage').text,
            status: element('#calibration-status').text,
        });
    };
    await context.pollCalibration('test-session');
    return {snapshots, element};
}

const running = (source, phase, reason) => ({
    status: 'running', source_kind: source, progress: {phase, reason},
});
const success = {status: 'success', result: {outcome: 'calibration'}};

test('restored saved-FITS run explains backward progress and repeated validation', async () => {
    const {snapshots} = await run([
        {status: 'queued', source_kind: 'database'},
        running('database', 'validating'),
        running('database', 'replacing_groups', 'evidence'),
        running('database', 'fitting'),
        running('database', 'validating'), success,
    ]);
    assert.deepEqual(snapshots.map(item => item.percent), ['72%', '96%', '89%', '91%', '96%']);
    assert.ok(snapshots.every(item => item.explanation));
    assert.equal(snapshots[2].stage, 'Checking more saved frames');
    assert.match(snapshots[2].status, /additional purple and normal/);
});

test('highlight search explains bright-area evidence and clears reassurance on failure', async () => {
    const {snapshots, element} = await run([
        running('database', 'replacing_groups', 'highlights'),
        {status: 'failed', source_kind: 'database', error: 'Insufficient evidence',
            sources_deleted_utc: '2026-10-01', report_available: true},
    ]);
    assert.match(snapshots[0].status, /usable bright areas/);
    assert.equal(element('#calibration-progress-explanation').visible, false);
    assert.equal(element('#calibration-progress').text, 'Failed');
    assert.equal(element('#calibration-failure-report-download').visible, true);
});

test('manual uploads do not show the saved-FITS retry explanation', async () => {
    const {snapshots} = await run([
        {status: 'queued', source_kind: 'upload'},
        running('upload', 'fitting'), running('upload', 'validating'), success,
    ]);
    assert.ok(snapshots.every(item => !item.explanation));
});
