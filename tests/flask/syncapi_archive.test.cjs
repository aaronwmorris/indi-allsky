const test = require('node:test');
const assert = require('node:assert/strict');
const {formatStatus, mount, schedulePayload} = require('../../indi_allsky/flask/static/js/syncapi-archive.js');

function statusText(state) { return Object.values(formatStatus(state)).join('\n'); }

function harness() {
    function element() {
        return {children: [], handlers: {},
            addEventListener(event, handler) { this.handlers[event] = handler; },
            querySelectorAll(selector) { if (selector === '[data-sync-status]') return this.children; return this.children.flatMap(label => label.children || []).filter(node => node.type === 'checkbox' && (selector === 'input' || node.checked)); }};
    }
    const nodes = Object.fromEntries(['start', 'cancel', 'types', 'status', 'error', 'schedule-controls',
        'schedule-enabled', 'schedule-interval', 'schedule-delay', 'upload-limit'].map(key => [key, element()]));
    nodes.status.children = ['schedule', 'next', 'run', 'cutoff', 'items', 'transferred', 'speed', 'file', 'progress', 'notice']
        .map(key => ({dataset: {syncStatus: key}, textContent: ''}));
    Object.defineProperty(nodes.status, 'textContent', {get() { return this.children.map(child => child.textContent).join('\n'); }});
    nodes.types.children = [{children: [{type: 'checkbox', value: 'image', checked: true}]},
        {children: [{type: 'checkbox', value: 'rawimage', checked: false}]}];
    nodes['schedule-enabled'].checked = false;
    nodes['schedule-interval'].value = '10';
    nodes['schedule-delay'].value = '3';
    nodes['upload-limit'].value = '0';
    const document = {handlers: {}, addEventListener(event, handler) { this.handlers[event] = handler; },
        dispatchEvent(event) { return this.handlers[event.type](event); },
        getElementById: id => nodes[id.replace('syncapi-run-', '')]};
    const panel = {dataset: {url: '/indi-allsky/ajax/syncapi/run', csrf: 'token'}};
    return {nodes, document, panel};
}

test('progress describes saved results, cutoff and pending cancellation', () => {
    const text = statusText({enabled: true, message: 'Interrupted', completed: 2, total: 4,
        skipped: 1, files: 3, bytes: 1048576, cutoff: '2026-09-13T12:00:00.157618', cancel_requested: true});
    assert.match(text, /2 of 4/);
    assert.match(text, /1.0 MiB/);
    assert.match(text, /2026-09-13 12:00:00/);
    assert.doesNotMatch(text, /157618/);
    assert.match(text, /Cancellation requested/);
});

for (const runState of ['cancelled', 'interrupted', 'failed', 'complete']) {
    test(`an enabled schedule takes priority over the previous ${runState} run`, () => {
        const state = {enabled: true, active: false, state: runState,
            message: 'Synchronization stopped. Press Sync now to continue.', completed: 1832, total: 115977,
            skipped: 0, files: 2749, bytes: 1666711552,
            schedule: {settings: {enabled: true}, message: 'Waiting for the next availability check.',
                next_action: '2026-09-13T22:17:20+02:00'}};
        const text = statusText(state);
        assert.match(text, /^Waiting for the next availability check\.\n2026-09-13 22:17:20/);
        assert.match(text, /Previous run: Synchronization stopped\./);
        assert.match(text, /1832 of 115977/);
        assert.doesNotMatch(text, /Press Sync now/);
        state.schedule.settings.enabled = false;
        assert.match(formatStatus(state).run, /^Synchronization stopped\. Press Sync now/);
        assert.doesNotMatch(statusText(state), /Previous run/);
    });
}

test('a successful configuration save immediately refreshes status and overtakes an older poll', async () => {
    const {nodes, document, panel} = harness();
    const polls = [], oldPoll = deferred();
    let reads = 0;
    const cancelled = {enabled: true, active: false, state: 'cancelled',
        message: 'Synchronization cancelled. Press Sync now to continue.',
        schedule: {settings: {enabled: false}, message: 'Paused by Cancel.'}};
    const applying = {...cancelled, schedule: {settings: {enabled: true}, state: 'applying',
        message: 'Schedule saved. Waiting for indi-allsky to apply the configuration.'}};
    const response = state => ({ok: true, json: async () => state});
    const fetcher = async () => {
        reads++;
        if (reads === 2) return oldPoll.promise;
        return response(reads === 1 ? cancelled : applying);
    };
    await mount(panel, document, fetcher, fn => polls.push(fn));
    const pending = polls.shift()();
    nodes['schedule-enabled'].checked = true;
    nodes['schedule-interval'].value = '7';
    await document.dispatchEvent({type: 'indi-allsky:config-saved'});
    assert.equal(reads, 3, 'Saving refreshes immediately without waiting five seconds');
    assert.match(nodes.status.textContent, /^Schedule saved\./);
    assert.doesNotMatch(nodes.status.textContent, /Press Sync now/);
    oldPoll.resolve(response(cancelled));
    await pending;
    assert.match(nodes.status.textContent, /^Schedule saved\./);
    assert.equal(nodes['schedule-enabled'].checked, true);
    assert.equal(nodes['schedule-interval'].value, '7');
    assert.equal(polls.length, 1, 'Saving does not create an extra polling loop');
});

test('polling only reads local status; start and cancel are explicit CSRF-protected requests', async () => {
    const {nodes, document, panel} = harness();
    const requests = [], scheduled = [];
    const fetcher = async (url, options) => {
        requests.push({url, options});
        const payload = options.body && JSON.parse(options.body);
        return {ok: true, json: async () => ({enabled: true, active: Boolean(payload), task_id: 42,
            state: payload ? 'queued' : 'idle', types: [{id: 'image', label: 'Images', selected: true}, {id: 'rawimage', label: 'RAW', selected: false}]})};
    };
    await mount(panel, document, fetcher, (fn, delay) => scheduled.push({fn, delay}));
    assert.equal(requests.length, 1);
    assert.equal(requests[0].options.method, undefined);
    assert.equal(nodes.start.disabled, false);
    await nodes.start.handlers.click();
    assert.deepEqual(JSON.parse(requests[1].options.body), {action: 'start', types: ['image'], upload_limit: 0});
    assert.equal(requests[1].options.headers['X-CSRFToken'], 'token');
    assert.equal(nodes.start.disabled, true);
    await nodes.cancel.handlers.click();
    assert.deepEqual(JSON.parse(requests[2].options.body), {action: 'cancel', task_id: 42});
    assert.ok(requests.every(item => item.url === panel.dataset.url));
    assert.equal(scheduled[0].delay, 5000);
});

test('failed start remains visible and does not trigger automatic retry', async () => {
    const {nodes, document, panel} = harness();
    const requests = [], scheduled = [];
    const fetcher = async (url, options) => {
        requests.push(options);
        return {ok: !options.body, json: async () => !options.body ?
            {enabled: true, active: false, types: [{id: 'image', label: 'Images', selected: true}]} : {error: 'Apply configuration first'}};
    };
    await mount(panel, document, fetcher, fn => scheduled.push(fn));
    await nodes.start.handlers.click();
    assert.equal(nodes.error.textContent, 'Apply configuration first');
    assert.equal(requests.length, 2);
    await scheduled.shift()();
    assert.equal(requests.length, 3);
    assert.equal(requests[2].method, undefined);
    assert.equal(nodes.error.textContent, 'Apply configuration first');
    assert.equal(nodes.start.disabled, false);
});

function htmlResponse(status) {
    return {ok: status < 400, status, json: async () => JSON.parse('<!DOCTYPE html><title>Server response</title>')};
}

for (const [name, failure, message] of [
    ['server error page', () => htmlResponse(502), /HTTP 502.*unreadable response/],
    ['unexpected HTML', () => htmlResponse(200), /HTTP 200.*unreadable response/],
    ['invalid status', () => ({ok: true, status: 200, json: async () => null}), /invalid status/],
    ['expired sign-in', () => ({status: 401}), /HTTP 401.*sign in/],
    ['redirected sign-in', () => ({redirected: true}), /redirected.*sign in/],
    ['connection loss', () => { throw new TypeError('Failed to fetch'); }, /connection interrupted/],
]) {
    test(`${name} preserves the last status and clears its polling error after recovery`, async () => {
        const {nodes, document, panel} = harness();
        const polls = [], requests = [];
        const fetcher = async (url, options) => {
            requests.push(options);
            if (requests.length === 2) return failure();
            return {ok: true, status: 200, json: async () => ({enabled: true, active: true, state: 'running',
                cancel_requested: false, completed: requests.length, total: 10, skipped: 0, files: 1, bytes: 1048576})};
        };
        await mount(panel, document, fetcher, fn => polls.push(fn));
        const previous = nodes.status.textContent;
        nodes['schedule-delay'].value = '7';
        await polls.shift()();
        assert.match(nodes.error.textContent, message);
        assert.doesNotMatch(nodes.error.textContent, /Unexpected token|DOCTYPE|Failed to fetch/);
        assert.equal(nodes.status.textContent, previous);
        assert.equal(nodes.cancel.disabled, false);
        await polls.shift()();
        assert.equal(nodes.error.textContent, '');
        assert.match(nodes.status.textContent, /3 of 10 items completed/);
        assert.equal(nodes['schedule-delay'].value, '7');
        assert.ok(requests.every(options => !options.method), 'Recovery only polls; it never starts or cancels a run');
    });
}

for (const action of ['start', 'cancel']) {
    for (const failure of ['HTML', 'network']) {
        test(`an unconfirmed ${action} after ${failure} is never automatically repeated`, async () => {
            const {nodes, document, panel} = harness();
            const polls = [], requests = [];
            const fetcher = async (url, options) => {
                requests.push(options);
                if (options.body) {
                    if (failure === 'network') throw new TypeError('Failed to fetch');
                    return htmlResponse(502);
                }
                return {ok: true, json: async () => ({enabled: true, active: action === 'cancel', task_id: 42})};
            };
            await mount(panel, document, fetcher, fn => polls.push(fn));
            await nodes[action].handlers.click();
            assert.match(nodes.error.textContent, /Could not confirm.*Check the refreshed status/);
            assert.doesNotMatch(nodes.error.textContent, /Unexpected token|Failed to fetch|retrying automatically/);
            const message = nodes.error.textContent;
            await polls.shift()();
            assert.equal(nodes.error.textContent, message);
            assert.equal(requests.filter(options => options.body).length, 1);
        });
    }
}

test('configuration payload includes current switch, timings and checkboxes without uploading', () => {
    const {nodes, document} = harness();
    nodes['schedule-enabled'].checked = true;
    nodes['schedule-interval'].value = '5';
    nodes['schedule-delay'].value = '0';
    nodes['upload-limit'].value = '256';
    nodes.types.querySelectorAll('input')[1].checked = true;
    assert.deepEqual(schedulePayload(document), {enabled: true, interval: 5, delay: 0, upload_limit: 256, types: ['image', 'rawimage']});
    nodes['schedule-delay'].value = '';
    assert.equal(schedulePayload(document).delay, null, 'An empty delay must not silently become zero');
});

test('Sync now uses unsaved checkboxes without changing scheduled content, even across newer polls', async () => {
    const {nodes, document, panel} = harness();
    const requests = [], polls = [];
    let revision = 'original';
    const fetcher = async (url, options) => {
        requests.push(options);
        return {ok: true, json: async () => ({enabled: true, active: false,
            schedule: {settings: {enabled: false, interval: 10, delay: 3, types: ['image'], revision},
                message: 'Waiting for receiver.', next_action: '2026-09-13T20:15:00+02:00'}})};
    };
    // Edits made before the first poll returns must also survive.
    nodes.types.querySelectorAll('input')[0].checked = false;
    nodes.types.querySelectorAll('input')[1].checked = true;
    nodes['schedule-interval'].value = '7';
    nodes['upload-limit'].value = '512';
    await mount(panel, document, fetcher, fn => polls.push(fn));
    revision = 'changed elsewhere';
    await polls.shift()();
    assert.equal(nodes['schedule-interval'].value, '7');
    await nodes.start.handlers.click();
    assert.deepEqual(JSON.parse(requests[2].body), {action: 'start', types: ['rawimage'], upload_limit: 512});
    assert.equal(requests.filter(options => options.method === 'POST').length, 1);
    assert.match(nodes.status.textContent, /Waiting for receiver/);
    assert.match(nodes.status.textContent, /2026-09-13 20:15:00/);
    nodes.types.querySelectorAll('input')[1].checked = false;
    await nodes.start.handlers.click();
    assert.equal(requests.length, 3);
    assert.match(nodes.error.textContent, /Select at least one/);
});

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return {promise, resolve};
}

test('current file progress is separate from acknowledged totals and hidden after a run', () => {
    const state = {enabled: true, active: true, completed: 1, total: 2, skipped: 0, files: 1, bytes: 1048576,
        upload: {name: 'night.mp4', bytes: 1048576, total: 2097152}};
    assert.match(statusText(state), /1 files, 1.0 MiB sent/);
    assert.equal(formatStatus(state).file, 'night.mp4');
    assert.match(formatStatus(state).progress, /1.0 of 2.0 MiB \(50%\)/);
    assert.doesNotMatch(statusText(state), /Waiting for the receiver/);
    state.upload.bytes = state.upload.total;
    assert.match(statusText(state), /Waiting for the receiver to acknowledge/);
    state.active = false;
    assert.doesNotMatch(statusText(state), /Uploading|Waiting for the receiver/);
});

test('recent speed uses decimal MB and only appears during a running task', () => {
    const state = {enabled: true, active: true, state: 'running', rates: {bytes: 250000, items: 0.5, files: 1.25}};
    assert.match(statusText(state), /0.25 MB\/s · 0.50 items\/s · 1.25 files\/s/);
    delete state.rates;
    assert.match(statusText(state), /Waiting for a progress update/);
    state.rates = {bytes: 0, items: 0, files: 0};
    assert.match(statusText(state), /0.00 MB\/s · 0.00 items\/s · 0.00 files\/s/);
    state.state = 'queued';
    assert.equal(formatStatus(state).speed, '');
    state.state = 'complete';
    state.active = false;
    assert.equal(formatStatus(state).speed, '');
});

test('status rows survive completion and clear transient values in place', async () => {
    const {nodes, document, panel} = harness();
    const polls = [];
    const rows = [...nodes.status.children];
    let current = {enabled: true, active: true, scheduled: true, state: 'running',
        upload: {name: 'night.mp4', bytes: 2097152, total: 2097152},
        rates: {bytes: 250000, items: 0.5, files: 1.25}};
    await mount(panel, document, async () => ({ok: true, json: async () => current}), fn => polls.push(fn));
    const row = key => rows.find(field => field.dataset.syncStatus === key);
    assert.match(row('run').textContent, /^Scheduled run/);
    assert.equal(row('file').textContent, 'night.mp4');
    assert.match(row('notice').textContent, /acknowledge/);
    current = {enabled: true, active: false, state: 'complete',
        schedule: {settings: {enabled: true}, message: 'Waiting for the next availability check.'}};
    await polls.shift()();
    assert.equal(nodes.status.children.length, rows.length);
    rows.forEach((field, index) => assert.equal(nodes.status.children[index], field));
    for (const key of ['speed', 'file', 'progress', 'notice']) {
        assert.equal(row(key).textContent, '');
        assert.equal(row(key).title, '');
    }
    assert.equal(row('schedule').textContent, 'Waiting for the next availability check.');
});

for (const checked of [false, true]) {
    test(`cancelling a manual run preserves the schedule checkbox (${checked})`, async () => {
        const {nodes, document, panel} = harness();
        nodes['schedule-enabled'].checked = checked;
        const current = {enabled: true, active: true, scheduled: false, task_id: 42,
            schedule: {settings: {enabled: true}}};
        await mount(panel, document, async (url, options) => ({ok: true,
            json: async () => ({...current, cancel_requested: Boolean(options.body)})}), () => {});
        await nodes.cancel.handlers.click();
        assert.equal(nodes['schedule-enabled'].checked, checked);
        assert.match(nodes.status.textContent, /Manual run/);
        assert.match(nodes.status.textContent, /Cancellation requested/);
    });
}

test('Sync now stays disabled through scheduler handoff and unlocks between runs', async () => {
    const {nodes, document, panel} = harness();
    const polls = [];
    let current = {enabled: true, active: false, schedule: {state: 'waiting', settings: {enabled: true}}};
    const fetcher = async () => ({ok: true, json: async () => current});
    await mount(panel, document, fetcher, fn => polls.push(fn));
    assert.equal(nodes.start.disabled, false);
    for (const active of [false, true, false]) {
        // The scheduler can report its queued/running job before task status
        // catches up, and keep that phase briefly after the worker finishes.
        current = {...current, active, schedule: {...current.schedule, state: 'running'}};
        const poll = polls.shift()();
        await poll;
        assert.equal(nodes.start.disabled, true);
    }
    for (const phase of ['waiting', 'checking', 'settling']) {
        current = {...current, schedule: {...current.schedule, state: phase}};
        await polls.shift()();
        assert.equal(nodes.start.disabled, false, 'Manual sync remains available before a scheduled run');
    }
});

for (const active of [false, true]) {
    test(`slow polling preserves controls and edits while ${active ? 'running' : 'idle'}`, async () => {
        const {nodes, document, panel} = harness();
        const polls = [], pending = deferred();
        const state = {enabled: true, active, task_id: 42, cancel_requested: false,
            types: [{id: 'image', label: 'Images', selected: true}],
            schedule: {settings: {enabled: true, interval: 10, delay: 3, types: ['image'], revision: 'saved'}}};
        const response = {ok: true, json: async () => state};
        let reads = 0;
        await mount(panel, document, async () => ++reads === 1 ? response : pending.promise, fn => polls.push(fn));
        const controls = ['start', 'cancel', 'types', 'schedule-controls'];
        const disabled = controls.map(key => nodes[key].disabled);
        nodes['schedule-interval'].value = '7';
        nodes.types.querySelectorAll('input')[0].checked = false;
        const poll = polls.shift()();
        assert.deepEqual(controls.map(key => nodes[key].disabled), disabled);
        assert.equal(nodes[active ? 'cancel' : 'start'].disabled, false);
        pending.resolve(response);
        await poll;
        assert.deepEqual(controls.map(key => nodes[key].disabled), disabled);
        assert.equal(nodes['schedule-interval'].value, '7');
        assert.equal(nodes.types.querySelectorAll('input')[0].checked, false);
    });
}

for (const staleFails of [false, true]) {
    for (const pollFinishesFirst of [false, true]) {
        test(`cancel overtakes a poll (${staleFails ? 'failed' : 'successful'}, finishes ${pollFinishesFirst ? 'before' : 'after'} command)`, async () => {
            const {nodes, document, panel} = harness();
            const polls = [], requests = [], pendingPoll = deferred(), pendingCommand = deferred();
            const running = {enabled: true, active: true, scheduled: true, task_id: 42,
                types: [{id: 'image', label: 'Images', selected: true}],
                schedule: {settings: {enabled: true, interval: 10, delay: 3, types: ['image'], revision: 'old'}}};
            const response = value => ({ok: true, json: async () => value});
            const fetcher = async (url, options) => {
                requests.push(options);
                if (options.body) return pendingCommand.promise;
                return requests.length === 1 ? response(running) : pendingPoll.promise;
            };
            await mount(panel, document, fetcher, fn => polls.push(fn));
            const poll = polls.shift()();
            const command = nodes.cancel.handlers.click();
            assert.equal(requests.length, 3, 'Cancel is sent without waiting for the poll');
            assert.deepEqual(JSON.parse(requests[2].body), {action: 'cancel', task_id: 42});
            assert.equal(nodes.cancel.disabled, true);
            await nodes.cancel.handlers.click();
            assert.equal(requests.length, 3, 'A pending command cannot be submitted twice');
            const settlePoll = async () => {
                pendingPoll.resolve(staleFails ? {ok: false, json: async () => ({error: 'Old poll failed'})} : response(running));
                await poll;
            };
            if (pollFinishesFirst) {
                await settlePoll();
                assert.equal(nodes.cancel.disabled, true, 'A stale poll cannot release the command lock');
                await polls.shift()();
                assert.equal(requests.length, 3, 'Polling waits while a command is pending');
            }
            pendingCommand.resolve(response({...running, cancel_requested: true,
                schedule: {settings: {...running.schedule.settings, enabled: false, revision: 'cancelled'}}}));
            await command;
            if (!pollFinishesFirst) await settlePoll();
            assert.equal(nodes.cancel.disabled, true, 'A stale poll cannot undo cancellation');
            assert.equal(nodes['schedule-enabled'].checked, false);
            assert.equal(nodes.error.textContent, '');
            assert.match(nodes.status.textContent, /Cancellation requested/);
        });
    }
}
