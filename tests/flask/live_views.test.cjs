// Also run by pytest. Exercise the browser entry points with controllable
// network, decoding and visibility events; no camera or browser cache needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const staticDir = path.resolve(__dirname, '../../indi_allsky/flask/static/js');

function browser(view, {sidebar = true, livePath = 'latest'} = {}) {
    let now = 0, nextId = 0;
    const timers = new Map(), elements = new Map(), requests = [], images = [], displays = [], draws = [];
    const handlers = new Map();
    const listen = (type, callback) => {
        if (!handlers.has(type)) handlers.set(type, []);
        handlers.get(type).push(callback);
    };

    class Element {
        constructor(id) {
            this.id = id;
            this.textContent = '';
            this.hidden = false;
            this.options = [];
            this.value = '';
            this.style = {setProperty() {}};
            this.classList = {toggle() {}};
            this.dataset = {};
        }
        addEventListener(type, callback) { this[type] = callback; }
        getContext() { return {drawImage: image => draws.push(image.src)}; }
        querySelector(key) {
            if (key === 'canvas' && this.id === 'live-view') return view === 'canvas' ? el('canvas') : null;
            return el(this.id + key);
        }
        querySelectorAll(selector) {
            return selector === '[data-station-state]' ? this.options : [];
        }
        set innerHTML(markup) {
            this.markup = markup;
            if (this.id === 'status_text') {
                this.options = Array.from(markup.matchAll(/<span data-station-state[^>]*>([^<]*)<\/span>/g), match => {
                    const marker = new Element('station');
                    marker.textContent = match[1];
                    return marker;
                });
            }
        }
        get innerHTML() { return this.markup; }
        after(node) { this.nextElementSibling = node; node.parentElement = this; }
        replaceWith(other) {
            elements.set(this.id, other);
            displays.push(other.src);
        }
        replaceChildren(...children) { this.options = children; }
        append(...children) {
            this.options.push(...children);
            for (const child of children) if (child instanceof Element) child.parentElement = this;
        }
        removeAttribute(key) { delete this[key]; }
    }
    function el(id) {
        if (!elements.has(id)) elements.set(id, new Element(id));
        return elements.get(id);
    }
    el('live-view').dataset = {interval: '31000', endpoint: '/indi-allsky/js/' + livePath + '?camera_id=3&night=auto'};
    if (sidebar) el('sidebar-live-status').dataset = {endpoint: '/indi-allsky/js/latest?camera_id=3&night=auto'};
    el('status_text').innerHTML = '<div>Status: <span data-station-state>RUNNING</span></div>';
    function byId(id) {
        if (id === 'live-view' && view === 'sidebar') return null;
        if (['message', 'live-age', 'live-time', 'live-server', 'live-status'].includes(id)) return null;
        if (!sidebar && ['sidebar-live-status', 'sidebar-live-detail', 'sidebar-image-age', 'sidebar-status-fallback', 'sidebar-station-fallback', 'status_text', 'live-retry', 'live-login', 'live-services', 'live-settings'].includes(id)) return null;
        return el(id);
    }
    const document = {baseURI: 'https://camera.test/indi-allsky/', hidden: false, addEventListener: listen,
        getElementById: byId,
        createElement: () => new Element(), createTextNode: text => text, querySelector: el};
    function schedule(callback, delay, repeat = false) {
        const id = ++nextId;
        timers.set(id, {callback, delay, at: now + delay, repeat});
        return id;
    }
    const setTimeout = (callback, delay) => schedule(callback, delay);
    const setInterval = (callback, delay) => schedule(callback, delay, true);
    const clearTimeout = id => timers.delete(id);
    const window = {setInterval, innerWidth: 640, innerHeight: 480, addEventListener: listen};
    const context = vm.createContext({URL, Date, Intl, AbortController, document, window, setTimeout, clearTimeout,
        performance: {now: () => now},
        Image: class extends Element {
            constructor() {super(); this.naturalWidth = 640; this.naturalHeight = 480; images.push(this);}
        },
        fetch: (url, options) => new Promise((resolve, reject) => {
            requests.push({url: new URL(url), options, fail: () => reject(new Error('network')),
                reply: (body, type = 'application/json', status = 200, redirected = false) => resolve({
                    json: async () => body, headers: {get: () => type}, ok: status >= 200 && status < 300, status, redirected,
                    url: redirected ? 'https://camera.test/indi-allsky/login' : url.toString(),
                })});
            // Deliberately do not settle fetch on signal.abort(). This lets a test
            // deliver an already-dispatched obsolete response after a wakeup.
        }),
    });
    const files = ['live_frames.js', 'latest_view.js'];
    for (const file of files) vm.runInContext(fs.readFileSync(path.join(staticDir, file), 'utf8'), context, {filename: file});
    const flush = () => new Promise(resolve => setImmediate(resolve));
    async function advance(ms) {
        const finish = now + ms;
        while (true) {
            const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
            if (!next || next[1].at > finish) break;
            const [id, timer] = next;
            now = timer.at;
            if (timer.repeat) timer.at += timer.delay;
            else timers.delete(id);
            timer.callback(); await flush();
        }
        now = finish;
    }
    const emit = (type, data = {}) => { for (const cb of handlers.get(type) || []) cb(data); };
    return {el, advance, requests, images, displays, draws, flush, emit, document, timers};
}

const running = {code:'running', label:'RUNNING', class_name:'tw:text-success'};
const latest = filename => ({latest_image: {url: filename, message: ''}, live_status:{station:running}});

for (const view of ['image', 'canvas']) {
    test(view + ': login HTML cannot kill the loop, recovered data draws immediately', async () => {
        const b = browser(view);
        b.requests[0].reply('<html>login</html>', 'text/html', 200, true);
        await b.flush();
        assert.equal(b.el('sidebar-station-fallback').textContent, 'SIGN IN REQUIRED');
        assert.equal(b.el('live-login').hidden, false);
        await b.advance(5000);
        b.requests[1].reply(latest('images/ok.jpg')); await b.flush();
        assert.equal(b.images.length, 1);
        b.images[0].onload();
        assert.deepEqual(view === 'canvas' ? b.draws : b.displays, ['images/ok.jpg']);
        assert.match(b.el('sidebar-image-age').title, /RUNNING.*web server reachable/);
        assert.equal(b.el('live-login').hidden, true);
        assert.equal(b.requests[1].options.cache, 'no-store');
    });
}

const detailed = (url, capturedAt, reason = null, now = '2026-11-08T03:05:00+01:00') => ({
    latest_image: {url, message: '', captured_at: capturedAt, frame_key: capturedAt, time_source: 'capture'},
    live_status: {now, stale_after_s: 90, reason, can_manage: false, station:running},
});

for (const view of ['image', 'canvas']) {
    test(view + ': age and camera time describe only the displayed frame, including while offline', async () => {
        const b = browser(view);
        const indicator = b.el('sidebar-image-age');
        assert.equal(b.requests.length, 1);
        assert.equal(b.requests[0].url.searchParams.get('live_status'), '1');
        const first = detailed('first', '2026-11-08T03:02:00+01:00');
        b.requests[0].reply(first); await b.flush();
        assert.match(indicator.textContent, /^Waiting for image/);
        b.images[0].onload();
        assert.match(indicator.textContent, /^Last image 3 min ago/);
        assert.match(indicator.title, /RUNNING.*web server reachable/);
        assert.match(indicator.title, /2026-11-08 03:02:00 UTC\+01:00/);
        await b.advance(5000);
        const next = detailed('next', first.live_status.now, null, '2026-11-08T03:05:05+01:00');
        b.requests[1].reply(next); await b.flush();
        assert.match(indicator.title, /03:02:00 UTC\+01:00/);
        assert.doesNotMatch(indicator.title, /03:05:00 UTC\+01:00/);
        b.images[1].onload();
        assert.match(indicator.title, /03:05:00 UTC\+01:00/);
        assert.equal(indicator.textContent, 'Last image 5 s ago');
        await b.advance(5000); b.requests[2].fail(); await b.flush();
        await b.advance(1000);
        assert.equal(indicator.textContent, 'Last image 11 s ago');
        assert.match(indicator.title, /CONNECTION LOST.*web server unreachable/);
        assert.equal(b.el('live-retry').hidden, false);
        b.el('live-retry').click();
        b.requests[3].reply(detailed('next', next.latest_image.captured_at, 'processing', '2026-11-08T03:05:11+01:00'));
        await b.flush();
        assert.equal(b.images.length, 2);
        assert.equal(indicator.textContent, 'Last image 11 s ago');
        assert.equal(b.el('live-retry').hidden, true);
    });

    test(view + ': frames still display without a status element in the page', async () => {
        const b = browser(view, {sidebar:false});
        b.requests[0].reply(detailed('shown.jpg', '2026-11-08T03:04:59+01:00'));
        await b.flush();
        b.images[0].onload();
        assert.deepEqual(view === 'canvas' ? b.draws : b.displays, ['shown.jpg']);
        await b.advance(5000);
        assert.equal(b.requests.length, 2);
    });
}

test('one poll updates the configured station status and frame age through an INDI outage and reconnection', async () => {
    const b = browser('sidebar');
    const at = '2026-11-08T03:04:57+01:00';
    const stop = {code:'no_indiserver', label:'NO INDISERVER', class_name:'tw:text-error'};
    const snapshot = (station, full = false) => {
        const payload = detailed('camera.jpg', at);
        payload.live_status.station = station;
        payload.live_status.can_manage = true;
        if (full) payload.status_text = '<div>Status: <span data-station-state>' + station.label + '</span></div>' +
            '<div>Battery 100%</div><div>Also <span data-station-state>' + station.label + '</span></div>';
        return payload;
    };
    const refresh = async () => { await b.advance(15000); return b.requests.at(-1); };
    assert.equal(b.requests.length, 1);
    assert.equal(b.requests[0].url.searchParams.get('status_details'), '1');
    b.requests[0].reply(snapshot(running, true)); await b.flush();
    const template = b.el('status_text'), age = b.el('sidebar-image-age');
    const first = template.options[0], second = template.options[1];
    assert.equal(first.nextElementSibling, age);
    assert.equal(second.nextElementSibling, undefined);
    assert.equal(b.el('sidebar-status-fallback').hidden, true);
    assert.match(template.innerHTML, /Battery 100%/);

    const next = await refresh();
    assert.equal(next.url.searchParams.has('status_details'), false);
    next.reply(snapshot(stop)); await b.flush();
    assert.equal(first.textContent, 'NO INDISERVER');
    assert.equal(second.textContent, 'NO INDISERVER');
    assert.equal(first.className, 'tw:text-error');
    assert.equal(age.textContent, 'Last image 3 s ago');
    assert.equal(b.el('sidebar-live-status').dataset.state, 'warning');
    assert.match(b.el('sidebar-live-detail').textContent, /cannot reach the INDI server/);
    assert.equal(b.el('live-retry').hidden, true);
    assert.equal(b.el('live-services').hidden, false);
    assert.match(age.title, /NO INDISERVER.*web server reachable/);

    (await refresh()).fail(); await b.flush();
    assert.equal(template.hidden, true);
    assert.equal(b.el('sidebar-status-fallback').hidden, false);
    assert.equal(b.el('sidebar-station-fallback').textContent, 'CONNECTION LOST');
    assert.equal(age.parentElement, b.el('sidebar-status-fallback'));
    b.el('live-retry').click();
    assert.equal(b.requests.at(-1).url.searchParams.get('status_details'), '1');
    b.requests.at(-1).reply(snapshot(running, true)); await b.flush();
    assert.equal(template.hidden, false);
    assert.equal(b.el('sidebar-status-fallback').hidden, true);
    assert.equal(template.options[0].textContent, 'RUNNING');
    assert.equal(template.options[0].className, 'tw:text-success');
    assert.equal(template.options[0].nextElementSibling, age);
    assert.deepEqual(b.images, []);
});

test('custom status templates without a station placeholder keep their content and get one fallback status', async () => {
    const b = browser('sidebar'), payload = detailed(null, null);
    payload.live_status.station = {code:'stopped', label:'STOPPED', class_name:'tw:text-primary'};
    payload.status_text = '<div><b>Battery:</b> 100%</div>';
    b.requests[0].reply(payload); await b.flush();
    assert.equal(b.el('status_text').innerHTML, payload.status_text);
    assert.equal(b.el('status_text').hidden, false);
    assert.equal(b.el('sidebar-status-fallback').hidden, false);
    assert.equal(b.el('sidebar-station-fallback').textContent, 'STOPPED');
    assert.equal(b.el('sidebar-image-age').parentElement, b.el('sidebar-status-fallback'));
    assert.equal(b.el('live-retry').hidden, true);
    delete payload.status_text;
    for (let i = 0; i < 4; i++) {
        await b.advance(15000);
        assert.equal(b.requests.at(-1).url.searchParams.has('status_details'), i === 3);
        b.requests.at(-1).reply(payload); await b.flush();
    }
    assert.equal(b.requests.length, 5);
    assert.equal(b.el('status_text').innerHTML, '<div><b>Battery:</b> 100%</div>');
});

test('specific remedies require a current authorization, and deliberate pauses are never retried manually', async () => {
    const b = browser('sidebar');
    const pause = detailed(null, null, 'paused');
    const update = async data => {
        b.emit('online'); b.requests.at(-1).reply(data); await b.flush();
    };
    b.requests[0].reply(pause); await b.flush();
    assert.match(b.el('sidebar-image-age').title, /Capture is paused/);
    assert.equal(b.el('sidebar-live-detail').textContent, 'Capture is paused.');
    assert.equal(b.el('live-settings').hidden, true);
    assert.equal(b.el('live-retry').hidden, true);
    assert.match(b.el('sidebar-image-age').textContent, /capture paused/);
    assert.doesNotMatch(b.el('sidebar-image-age').textContent, /settings/i);
    pause.live_status.can_sign_in_to_manage = true;
    await update(pause);
    assert.equal(b.el('live-login').hidden, false);
    assert.equal(b.el('live-settings').hidden, true);
    pause.live_status.can_sign_in_to_manage = false;
    pause.live_status.can_manage = true;
    await update(pause);
    assert.equal(b.el('live-settings').hidden, false);
    pause.live_status.reason = 'archive_readonly';
    await update(pause);
    assert.equal(b.el('live-settings').hidden, true);
    assert.equal(b.el('live-services').hidden, false);
    assert.match(b.el('sidebar-image-age').title, /write access/);
    assert.match(b.el('sidebar-live-detail').textContent, /write access/);
    b.emit('online'); b.requests.at(-1).reply({}, 'application/json', 403);
    await b.flush();
    assert.equal(b.el('live-services').hidden, true);
    assert.equal(b.el('live-login').hidden, true);
    assert.equal(b.el('live-retry').hidden, true);
    b.emit('online'); b.requests.at(-1).reply({}, 'application/json', 401);
    await b.flush();
    assert.equal(b.el('live-login').hidden, false);
});

test('ambiguous camera timestamps do not inherit the timestamp or age of the previous frame', async () => {
    const b = browser('image');
    b.requests[0].reply(detailed('first', '2026-11-08T03:04:59+01:00')); await b.flush();
    b.images[0].onload();
    const entry = detailed('ambiguous', null);
    entry.latest_image.frame_key = 'image:2';
    await b.advance(5000); b.requests[1].reply(entry); await b.flush(); b.images[1].onload();
    assert.doesNotMatch(b.el('sidebar-image-age').title, /03:04:59/);
    assert.match(b.el('sidebar-image-age').textContent, /^Image time unknown/);
});

test('the sidebar tooltip identifies file times and distinguishes the repeated local hour', async () => {
    const b = browser('image');
    const indicator = b.el('sidebar-image-age');
    for (const [index, offset] of ['+02:00', '+01:00'].entries()) {
        if (index) await b.advance(5000);
        const entry = detailed('file-' + index, '2026-10-25T02:15:00' + offset,
            null, '2026-10-25T02:15:02' + offset);
        entry.latest_image.time_source = 'file';
        b.requests[index].reply(entry);
        await b.flush();
        b.images[index].onload();
        assert.equal(indicator.textContent, 'Last image 2 s ago');
        assert.ok(indicator.title.includes('File time 2026-10-25 02:15:00 UTC' + offset));
        assert.equal(b.el('sidebar-live-detail').textContent, '');
    }
});

test('a clock correction never turns a genuinely future displayed timestamp into a freshly captured image', async () => {
    const b = browser('image', {sidebar: true});
    const captured = '2026-11-08T03:05:01+01:00';
    b.requests[0].reply(detailed('shown.jpg', captured));
    await b.flush(); b.images[0].onload();
    const indicator = b.el('sidebar-image-age');
    assert.match(indicator.textContent, /^Last image 0 s ago/);
    await b.advance(5000);
    b.requests[1].reply(detailed(null, null, 'no_recent_image', '2026-11-08T02:55:05+01:00'));
    await b.flush();
    assert.match(indicator.title, /03:05:01 UTC\+01:00/);
    assert.match(indicator.title, /Check the camera time and time zone/);
    assert.equal(b.el('live-retry').hidden, false);
    assert.equal(b.el('sidebar-image-age').textContent, 'Image time ahead of camera · check clock');
    b.el('live-retry').click();
    b.requests[2].reply(detailed('new-frame.jpg', '2026-11-08T02:55:05+01:00', null, '2026-11-08T02:55:08+01:00'));
    await b.flush(); b.images[1].onload();
    assert.equal(indicator.textContent, 'Last image 3 s ago');
    assert.equal(b.el('live-retry').hidden, true);
});

test('on other pages the sidebar polls JSON at a low rate without downloading images', async () => {
    const b = browser('sidebar', {sidebar: true});
    b.requests[0].reply(detailed('not-fetched', '2026-11-08T03:04:57+01:00'));
    await b.flush();
    assert.equal(b.el('sidebar-image-age').textContent, 'Last image 3 s ago');
    await b.advance(12000);
    assert.equal(b.requests.length, 1);
    assert.equal(b.el('sidebar-image-age').textContent, 'Last image 15 s ago');
    await b.advance(3000);
    assert.equal(b.requests.length, 2);
    assert.equal(b.images.length, 0);
    b.requests[1].fail();
    await b.flush();
    assert.equal(b.el('live-retry').hidden, false);
    b.el('live-retry').click();
    assert.equal(b.requests.length, 3);
    b.requests[2].reply(detailed('new.jpg', '2026-11-08T03:04:59+01:00'));
    await b.flush();
    assert.equal(b.el('live-retry').hidden, true);
    assert.deepEqual(b.images, []);
});

test('panorama polls and sidebar capture polls remain independent', async () => {
    const b = browser('canvas', {sidebar: true, livePath:'latest_panorama'});
    assert.equal(b.requests.length, 2);
    b.requests[0].reply(detailed('panorama.jpg', '2026-11-08T03:01:00+01:00'));
    b.requests[1].reply(detailed('normal.jpg', '2026-11-08T03:04:51+01:00', 'capture_recovering'));
    await b.flush();
    b.images[0].onload();
    assert.equal(b.el('sidebar-image-age').textContent, 'Last image 9 s ago · recovering capture');
    assert.doesNotMatch(b.el('sidebar-image-age').title, /03:01:00/);
    assert.deepEqual(b.draws, ['panorama.jpg']);
    assert.equal(b.images.length, 1);
});

test('a slow completed frame displays before the newest queued frame; a failed image retains it', async () => {
    const b = browser('image');
    b.requests[0].reply(latest('first')); await b.flush();
    await b.advance(5000); b.requests[1].reply(latest('obsolete')); await b.flush();
    await b.advance(5000); b.requests[2].reply(latest('newest')); await b.flush();
    assert.equal(b.images.length, 1);
    b.images[0].onload();
    assert.deepEqual(b.displays, ['first']);
    assert.equal(b.images[1].src, 'newest');
    b.images[1].onerror();
    assert.deepEqual(b.displays, ['first']);
    assert.match(b.el('sidebar-image-age').title, /could not be loaded/i);
    await b.advance(5000); b.requests[3].reply(latest('newest')); await b.flush();
    b.images[2].onload(); assert.deepEqual(b.displays, ['first', 'newest']);
});

test('returning from sleep cancels old HTTP and JPEG callbacks; a bfcache return refreshes', async () => {
    const b = browser('canvas');
    b.requests[0].reply(latest('old')); await b.flush();
    const lateImage = b.images[0].onload;
    await b.advance(5000);
    b.document.hidden = true; b.emit('visibilitychange');
    assert.equal(b.requests[1].options.signal.aborted, true);
    assert.equal(b.images[0].onload, null);
    await b.advance(15000); assert.equal(b.requests.length, 2);
    b.document.hidden = false; b.emit('visibilitychange');
    b.requests[2].reply(latest('new')); await b.flush();
    b.requests[1].reply(latest('stale')); lateImage(); await b.flush();
    assert.equal(b.images.length, 2);
    b.images[1].onload(); assert.deepEqual(b.draws, ['new']);
    b.emit('pageshow', {persisted: true});
    assert.equal(b.requests.length, 4);
});

test('a hanging JPEG times out and the same key becomes retriable', async () => {
    const b = browser('image');
    b.requests[0].reply(latest('unchanged')); await b.flush();
    for (let i = 1; i < 6; i++) {
        await b.advance(5000); b.requests[i].reply(latest('unchanged')); await b.flush();
        assert.equal(b.images.length, 1);
    }
    await b.advance(5000);
    assert.match(b.el('sidebar-image-age').title, /timed out/);
    b.requests[6].reply(latest('unchanged')); await b.flush();
    assert.equal(b.images.length, 2);
    b.images[1].onload(); assert.deepEqual(b.displays, ['unchanged']);
});
