// Also run by test_notification_polling.py as part of the pytest suite.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function page() {
    let now = 0;
    let timerId = 0;
    let ready;
    const timers = new Map();
    const elements = new Map();
    const handlers = new Map();
    const requests = [];
    const schedule = (callback, delay, repeat = false) => {
        const id = ++timerId;
        timers.set(id, { callback, delay, repeat, at: now + delay });
        return id;
    };
    const document = {
        body: {},
        querySelectorAll: () => [],
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, {
                open: false, textContent: '', style: {}, shown: 0,
                classList: { toggle() {}, contains: () => false },
                addEventListener() {},
                showModal() { this.open = true; this.shown++; },
            });
            return elements.get(id);
        },
    };
    const $ = (selector) => ({
        ready(callback) { ready = callback; },
        on(event, callback) { handlers.set(`${selector}:${event}`, callback); return this; },
        off() { handlers.delete(`${selector}:click`); return this; },
        attr() {}, prop() {}, html() {},
    });
    $.ajaxSetup = () => {};
    $.ajax = (settings) => {
        let finished = false;
        let timeout;
        const finish = (data, error) => {
            assert.equal(finished, false, 'request must complete only once');
            finished = true;
            timers.delete(timeout);
            if (error) settings.error?.({}, error);
            else settings.success?.(data);
            settings.complete?.({}, error || 'success');
        };
        if (settings.timeout) timeout = schedule(() => finish(null, 'timeout'), settings.timeout);
        requests.push({ ...settings, respond: (data) => finish(data), fail: (error) => finish(null, error) });
    };
    const context = vm.createContext({
        $, document, window: { innerWidth: 1200 },
        ResizeObserver: class { observe() {} },
        localStorage: { getItem() { return null; }, setItem() {} },
        setTimeout: (callback, delay) => schedule(callback, delay),
        setInterval: (callback, delay) => schedule(callback, delay, true),
    });
    const template = fs.readFileSync(path.join(__dirname, '../../indi_allsky/flask/templates/base.html'), 'utf8');
    const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]
        .replace(/\{\{ url_for\('indi_allsky\.([^']+)'\) \}\}/g, '/$1')
        .replace(/\{\{[\s\S]*?\}\}/g, '0');
    vm.runInContext(script, context, { filename: 'base.html' });
    ready();

    function advance(milliseconds) {
        const target = now + milliseconds;
        while (true) {
            const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
            if (!next || next[1].at > target) break;
            const [id, timer] = next;
            now = timer.at;
            if (timer.repeat) timer.at += timer.delay;
            else timers.delete(id);
            timer.callback();
        }
        now = target;
    }
    const modal = document.getElementById('notificationModal');
    return {
        advance, modal, requests,
        notices: () => requests.filter(r => r.url === '/ajax_notification_view'),
        text: () => document.getElementById('notification_body').textContent,
        acknowledge() {
            handlers.get('#ack_button:click')();
            modal.open = false; // Native <form method="dialog"> default action.
        },
    };
}

const notice = (id) => ({ id, category: 'general', createDate: '2026-09-25 00:00:00', notification: `Failure ${id}` });

test('an alert created after 35 minutes appears without reloading the page', () => {
    const p = page();
    assert.equal(p.notices().length, 1);
    p.notices()[0].respond({ id: 0 });
    assert.equal(p.modal.open, false);
    for (let minute = 1; minute <= 35; minute++) {
        p.advance(59999);
        assert.equal(p.notices().length, minute);
        p.advance(1);
        assert.equal(p.notices().length, minute + 1);
        p.notices().at(-1).respond(minute === 35 ? notice(7) : { id: 0 });
    }
    assert.equal(p.modal.open, true);
    assert.equal(p.text(), 'Failure 7');
    assert.equal(p.modal.shown, 1);
});

for (const error of ['error', 'parsererror']) {
    test(`notification polling recovers after ${error}`, () => {
        const p = page();
        p.notices()[0].fail(error);
        p.advance(60000);
        assert.equal(p.notices().length, 2);
        p.notices()[1].respond(notice(8));
        assert.equal(p.text(), 'Failure 8');
        assert.equal(p.modal.open, true);
    });
}

test('a hung notification request times out and polling resumes', () => {
    const p = page();
    p.advance(60000);
    assert.equal(p.notices().length, 2);
    p.notices()[1].respond(notice(9));
    assert.equal(p.modal.open, true);
    assert.equal(p.text(), 'Failure 9');
});

test('status polling failure does not stop notification checks', () => {
    const p = page();
    p.notices()[0].respond({ id: 0 });
    p.requests.find(r => r.url === '/ajax_status_update_view').fail('error');
    p.advance(60000);
    assert.equal(p.notices().length, 2);
    p.notices()[1].respond(notice(10));
    assert.equal(p.modal.open, true);
});

test('polling does not replace a notification while it is being read', () => {
    const p = page();
    p.notices()[0].respond(notice(11));
    p.advance(180000);
    assert.equal(p.notices().length, 1);
    assert.equal(p.text(), 'Failure 11');
    assert.equal(p.modal.shown, 1);
});

test('polling waits for acknowledgement and preserves the next-notification flow', () => {
    const p = page();
    p.notices()[0].respond(notice(12));
    p.advance(59000);
    p.acknowledge();
    const ack = p.notices()[1];
    assert.equal(ack.type, 'POST');
    assert.equal(JSON.parse(ack.data).ack_id, 12);
    p.advance(1000);
    assert.equal(p.notices().length, 2, 'must not fetch a stale alert during acknowledgement');
    ack.respond(notice(13));
    assert.equal(p.modal.open, true);
    assert.equal(p.text(), 'Failure 13');
    p.acknowledge();
    assert.equal(JSON.parse(p.notices()[2].data).ack_id, 13);
    p.notices()[2].respond({ id: 0 });
    p.advance(60000);
    assert.equal(p.notices().length, 4);
    p.notices()[3].respond(notice(14));
    assert.equal(p.modal.open, true);
    assert.equal(p.text(), 'Failure 14');
});

for (const timeout of [false, true]) {
    test(`polling recovers after acknowledgement ${timeout ? 'timeout' : 'failure'}`, () => {
        const p = page();
        p.notices()[0].respond(notice(15));
        p.advance(59000);
        p.acknowledge();
        if (timeout) p.advance(10000);
        else p.notices()[1].fail('error');
        p.advance(timeout ? 51000 : 1000);
        assert.equal(p.notices().length, 3);
        p.notices()[2].respond(notice(15));
        assert.equal(p.modal.open, true);
        assert.equal(p.text(), 'Failure 15');
    });
}
