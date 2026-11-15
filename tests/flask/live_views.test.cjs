// Also run by pytest. Exercise the browser entry points with controllable
// network, decoding and visibility events; no camera or browser cache needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const staticDir = path.resolve(__dirname, '../../indi_allsky/flask/static/js');

function browser(view, {saved = new Map()} = {}) {
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
            this.dataset = {};
            this.options = [];
            this.value = '';
            this.style = {setProperty() {}};
            this.classList = {toggle() {}};
        }
        addEventListener(type, callback) { this[type] = callback; }
        focus() {}
        getContext() { return {drawImage: image => draws.push(image.src)}; }
        querySelector(key) {
            if (key === 'canvas' && this.id === 'live-view') return view === 'canvas' ? el('canvas') : null;
            return el(this.id + key);
        }
        replaceWith(other) {
            elements.set(this.id, other);
            displays.push(other.src);
        }
        replaceChildren(...children) { this.options = children; }
        append(...children) { this.options.push(...children); }
        removeAttribute(key) { delete this[key]; }
        setAttribute(key, value) { this[key] = value; }
    }
    function el(id) {
        if (!elements.has(id)) elements.set(id, new Element(id));
        return elements.get(id);
    }
    el('companion').dataset = {cameraId: '3', refreshMs: '30000', staleMs: '90000', endpoint: '/indi-allsky/js/companion?camera_id=3'};
    el('live-view').dataset = {interval: '31000', endpoint: '/indi-allsky/js/latest?camera_id=3&night=auto'};
    const document = {baseURI: 'https://camera.test/indi-allsky/', hidden: false, addEventListener: listen,
        getElementById: el, createElement: () => new Element(), createTextNode: text => text, querySelector: el};
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
        performance: {now: () => now}, localStorage: {getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value)},
        Option: class {constructor(label, value) {this.label = label; this.value = value;}},
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
    const files = ['live_frames.js', ...(view === 'companion' ? ['companion_targets.js', 'companion.js'] : ['latest_view.js'])];
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

const latest = filename => ({latest_image: {url: filename, message: ''}});
const frame = (id = 0) => ({url: 'images/' + id + '.jpg', captured_at: '2026-11-07T21:00:0' + id + '+01:00', time_source: 'capture'});
const status = image => ({image, now: '2026-11-07T21:00:10+01:00', time_zone: 'Europe/Berlin', offset_minutes: 60});
const full = image => ({...status(image), astronomy: {moon_phase: 'New Moon', moon_illumination: 0}, metrics: [], defaults: [], series: []});

test('companion resolves, saves and removes both named and J2000 targets per camera', async () => {
    const saved = new Map();
    const b = browser('companion', {saved});
    b.el('target-name').value = 'M31';
    const submit = () => b.el('target-form').submit({preventDefault() {}});
    const first = submit();
    assert.equal(b.requests.at(-1).url.searchParams.get('resolve'), 'M31');
    b.requests.at(-1).reply({target: {label: 'M31', ra_deg: 10.68, dec_deg: 41.27}});
    await first;
    b.el('target-mode').value = 'coords';
    b.el('target-mode').change();
    b.el('target-ra').value = '18:30:00';
    b.el('target-dec').value = '-12:30:00';
    b.el('target-label').value = 'My mosaic';
    const second = submit();
    assert.equal(b.requests.at(-1).url.searchParams.get('ra'), '18:30:00');
    assert.equal(b.requests.at(-1).url.searchParams.get('dec'), '-12:30:00');
    b.requests.at(-1).reply({target: {label: '277.5°, −12.5°', ra_deg: 277.5, dec_deg: -12.5}});
    await second;
    assert.deepEqual(JSON.parse(saved.get('allsky-companion-targets-3')).map(t => t.label), ['M31', 'My mosaic']);
    const reopened = browser('companion', {saved});
    assert.equal(reopened.el('target-open').textContent, 'Targets (2)');
    reopened.el('target-list').options[0].options[1].click();
    assert.equal(reopened.el('target-open').textContent, 'Targets (1)');
    assert.equal(JSON.parse(saved.get('allsky-companion-targets-3'))[0].label, 'My mosaic');
    assert.match(reopened.el('target-status').textContent, /saved, aligned image/);
});

test('an offline miss offers one explicit CDS search for that name and saves the result', async () => {
    const saved = new Map();
    const b = browser('companion', {saved});
    const form = b.el('target-form');
    const name = b.el('target-name');
    const online = b.el('target-online');
    const queries = () => b.requests.filter(r => r.url.searchParams.has('resolve'));
    name.value = '3C 273';
    form.input();
    assert.equal(queries().length, 0);
    assert.equal(online.hidden, true);
    const first = form.submit({preventDefault() {}});
    assert.equal(queries()[0].url.searchParams.has('online'), false);
    queries()[0].reply({code: 'unknown_name', error: 'Unknown object.'}, 'application/json', 400);
    await first;
    assert.equal(online.hidden, false);
    assert.equal(queries().length, 1);
    const second = online.click();
    assert.deepEqual([...queries()[1].url.searchParams], [['camera_id','3'], ['resolve','3C 273'], ['online','1']]);
    assert.equal(queries()[1].url.origin, 'https://camera.test');
    queries()[1].reply({code: 'catalog_unavailable', error: 'CDS is unavailable.'}, 'application/json', 503);
    await second;
    assert.equal(online.hidden, false);
    assert.equal(online.disabled, false);
    assert.equal(queries().length, 2);
    const retry = online.click();
    queries()[2].reply({target: {label: '3C 273', ra_deg: 187.27, dec_deg: 2.05}});
    await retry;
    assert.equal(online.hidden, true);
    assert.equal(name.value, '');
    assert.equal(JSON.parse(saved.get('allsky-companion-targets-3'))[0].label, '3C 273');
});

test('editing or closing discards stale lookups and coordinate entry never offers CDS', async () => {
    const b = browser('companion');
    const form = b.el('target-form');
    const online = b.el('target-online');
    const submit = () => form.submit({preventDefault() {}});
    const miss = request => request.reply({code: 'unknown_name', error: 'Unknown object.'}, 'application/json', 400);
    b.el('target-name').value = 'First';
    const first = submit();
    const old = b.requests.at(-1);
    b.el('target-name').value = 'Second';
    form.input();
    assert.equal(old.options.signal.aborted,true);
    miss(old);
    await first;
    assert.equal(online.hidden, true);
    const second = submit();
    miss(b.requests.at(-1));
    await second;
    const remote = online.click();
    const inFlight = b.requests.at(-1);
    b.el('target-dialog').close();
    assert.equal(inFlight.options.signal.aborted, true);
    inFlight.reply({target: {label: 'Second', ra_deg: 12, dec_deg: 15}});
    await remote;
    assert.equal(b.el('target-open').textContent, 'Targets');
    assert.equal(online.hidden, true);
    b.el('target-mode').value = 'coords';
    b.el('target-mode').change();
    const coordinates = submit();
    miss(b.requests.at(-1));
    await coordinates;
    assert.equal(online.hidden, true);
    const count = b.requests.length;
    await online.click();
    assert.equal(b.requests.length, count);
});

test('companion batches targets and never applies obsolete positions to another displayed frame', async () => {
    const targets = Array.from({length: 65}, (_, i) => ({label: 'Target ' + i, ra_deg: i, dec_deg: 10}));
    const b = browser('companion', {saved: new Map([['allsky-companion-targets-3', JSON.stringify(targets)]])});
    const images = () => b.requests.filter(r => r.url.searchParams.has('image_only'));
    const projections = () => b.requests.filter(r => r.url.searchParams.has('frame'));
    const old = {...frame(1), id: 7};
    images()[0].reply(status(old)); await b.flush();
    assert.equal(projections().length, 0);
    b.images[0].onload(); await b.flush();
    const oldRequest = projections()[0];
    assert.equal(oldRequest.url.searchParams.get('frame'), '7');
    await b.advance(2000);
    images().at(-1).reply(status({...frame(2), id: 8})); await b.flush();
    assert.equal(projections().length, 1);
    const fresh = b.images[1];
    fresh.clientWidth = 240; fresh.clientHeight = 220;
    fresh.onload(); await b.flush();
    oldRequest.reply({frame: 7, state: 'ready', points: Array(32).fill({x: 0, y: 0})});
    await b.flush();
    assert.equal(b.el('target-markers').options.length, 0);
    for (const count of [32, 32, 1]) {
        const req = projections().at(-1);
        assert.equal(req.url.searchParams.get('frame'), '8');
        assert.equal(req.url.searchParams.getAll('target').length, count);
        req.reply({frame: 8, state: 'ready', points: Array(count).fill(count === 1 ? null : {x: .75, y: .25})});
        await b.flush();
    }
    const layer = b.el('target-markers');
    assert.deepEqual([layer.style.width, layer.style.height], ['240px', '180px']);
    assert.equal(layer.options.length, 64);
    assert.deepEqual([layer.options[0].style.left, layer.options[0].style.top], ['75%', '25%']);
    await b.advance(2000);
    images().at(-1).reply(status({...frame(3), time_source: 'file'})); await b.flush();
    b.images[2].onload(); await b.flush();
    assert.equal(layer.options.length, 0);
    assert.match(b.el('target-status').textContent, /saved, aligned image/);
});

for (const view of ['image', 'canvas']) {
    test(view + ': login HTML cannot kill the loop, recovered data draws immediately', async () => {
        const b = browser(view);
        b.requests[0].reply('<html>login</html>', 'text/html', 200, true);
        await b.flush();
        assert.match(b.el('message').textContent, /Sign in/);
        await b.advance(5000);
        b.requests[1].reply(latest('images/ok.jpg')); await b.flush();
        assert.equal(b.images.length, 1);
        b.images[0].onload();
        assert.deepEqual(view === 'canvas' ? b.draws : b.displays, ['images/ok.jpg']);
        assert.equal(b.el('message').textContent, '');
        assert.equal(b.requests[1].options.cache, 'no-store');
    });
}

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
    assert.match(b.el('message').textContent, /could not be loaded/);
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
    assert.match(b.el('message').textContent, /timed out/);
    b.requests[6].reply(latest('unchanged')); await b.flush();
    assert.equal(b.images.length, 2);
    b.images[1].onload(); assert.deepEqual(b.displays, ['unchanged']);
});

test('companion image checks proceed through repeated or slow detail failures', async () => {
    const b = browser('companion');
    const only = () => b.requests.filter(r => r.url.searchParams.has('image_only'));
    const details = () => b.requests.filter(r => !r.url.searchParams.has('image_only'));
    assert.equal(only().length, 1); assert.equal(details().length, 1);
    only()[0].reply(status(frame())); await b.flush();
    b.images[0].onload();
    for (let i = 1; i < 4; i++) {
        await b.advance(2000); only()[i].reply(status(frame(i))); await b.flush();
        b.images[i].onload();
    }
    assert.equal(details().length, 1);
    details()[0].reply(null, 'application/json', 503); await b.flush();
    assert.match(b.el('connection-message').textContent, /history/);
    await b.advance(2000); only()[4].reply(status(frame(4))); await b.flush();
    b.images[4].onload();
    assert.equal(b.el('image-time').dateTime, frame(4).captured_at);
    assert.equal(b.displays.length, 5);
});

test('companion differentiates missing, transferring, paused, offline and authentication states', async () => {
    const b = browser('companion');
    let read = b.requests[0];
    const message = () => b.el('connection-message').textContent;
    read.reply(status(null)); b.requests[1].reply(full(null)); await b.flush();
    assert.match(message(), /Pi online · no new image/);
    await b.advance(2000); read = b.requests.at(-1);
    read.reply(status(frame())); await b.flush(); await b.advance(1000);
    assert.match(message(), /New capture available · loading image/);
    b.images[0].onload(); assert.equal(message(), '');
    await b.advance(1000); b.requests.at(-1).fail(); await b.flush();
    assert.match(message(), /Lost connection to the Pi/);
    b.emit('online');
    b.requests.at(-2).reply({...status(frame()), capture_paused: true}); b.requests.at(-1).reply(full(null)); await b.flush();
    assert.match(message(), /capture paused/);
    assert.equal(b.displays.length, 1);
    await b.advance(2000); b.requests.at(-1).reply('login', 'text/html', 200, true); await b.flush();
    assert.match(message(), /Sign in again/);
    assert.equal(b.displays.length, 1);
});

test('companion uses the charge reported by the HAT at each color threshold', async () => {
    const b = browser('companion');
    const snapshot = full(null);
    b.requests[0].reply(snapshot); b.requests[1].reply(snapshot); await b.flush();
    for (const [value, level] of [[100, 'high'], [20, 'high'], [19, 'medium'], [10, 'medium'], [9, 'low'], [0, 'low']]) {
        snapshot.battery = {value, expires_at: '2026-11-07T22:00:00+01:00'};
        b.emit('online');
        b.requests.at(-2).reply(snapshot); b.requests.at(-1).reply(snapshot); await b.flush();
        const icon = b.el('battery');
        assert.equal(icon.dataset.level, level);
        assert.equal(icon['aria-label'], 'Battery ' + value + '%, ' + level + ' charge');
    }
});

test('companion hides an absent battery, shows a genuine zero and expires the reading offline', async () => {
    const b = browser('companion');
    const snapshot = full(null);
    const icon = b.el('battery');
    b.requests[0].reply(snapshot); b.requests[1].reply(snapshot); await b.flush();
    assert.equal(icon.hidden, true);
    snapshot.battery = {value: 0, expires_at: '2026-11-07T21:00:12+01:00'};
    b.emit('online');
    b.requests.at(-2).reply(snapshot); b.requests.at(-1).reply(snapshot); await b.flush();
    assert.equal(icon.hidden, false);
    assert.equal(b.el('battery-value').textContent, '0%');
    assert.equal(icon['aria-label'], 'Battery 0%, low charge');
    assert.equal(icon.dataset.level, 'low');
    await b.advance(3000);
    assert.equal(b.el('battery-value').textContent, '–');
    assert.equal(icon.title, 'Battery reading unavailable');
    assert.equal(icon.dataset.level, 'unknown');
});

test('companion formats English readings and keeps the date and offset of each camera event', async () => {
    const b = browser('companion');
    const image = {...frame(), captured_at: '2026-10-25T00:00:00+02:00'};
    const payload = {...full(image), now: '2026-10-25T00:00:10+02:00', offset_minutes: 120};
    Object.assign(payload.astronomy, {moon_rise: '2026-10-25T00:15:00+02:00', moon_illumination: 0.5});
    const metric = {id: 'sensor_user_35', label: 'Sky brightness', unit: 'lx'};
    payload.metrics = [metric];
    payload.defaults = [metric.id];
    payload.series = [{...metric, points: [['2026-10-25T02:30:00+02:00', 1.25]]}];
    b.requests[0].reply(payload);
    b.requests[1].reply(payload);
    await b.flush();
    b.images[0].onload();
    assert.equal(b.el('clock').textContent, '00:00:10');
    assert.equal(b.el('image-time').options[1].textContent, '2026-10-25');
    assert.equal(b.el('image-age').textContent, '10 s ago');
    const rise = b.el('moon_rise').options[0];
    assert.equal(rise.dateTime, payload.astronomy.moon_rise);
    assert.deepEqual(rise.options.map(child => child.textContent), ['00:15', 'Oct 25']);
    assert.equal(b.el('moon-phase').textContent, 'New Moon · 0.5%');
    const reading = b.el('chart-slot-1.chart-value');
    assert.equal(reading.textContent, '1.25 lx');
    assert.equal(reading.title, 'Last reading at 02:30 UTC+02:00');
    // The same local time occurs again after the camera switches to standard time.
    payload.series[0].points.push(['2026-10-25T02:30:00+01:00', 0.025]);
    b.emit('online');
    b.requests.at(-2).reply(payload);
    b.requests.at(-1).reply(payload);
    await b.flush();
    assert.equal(reading.textContent, '0.025 lx');
    assert.equal(reading.title, 'Last reading at 02:30 UTC+01:00');
});

test('companion reports orientation only on a current reply from an enabled camera', async () => {
    const b = browser('companion');
    const orientation = b.el('orientation');
    b.requests[0].reply({...status(null), orientation: 'pending'});
    b.requests[1].reply(full(null)); await b.flush();
    assert.equal(orientation.textContent, 'Orientation pending');
    assert.equal(orientation.hidden, false);
    await b.advance(2000);
    b.requests.at(-1).reply({...status(null), orientation: 'aligned'}); await b.flush();
    assert.equal(orientation.textContent, 'Aligned by stars');
    await b.advance(2000); b.requests.at(-1).fail(); await b.flush();
    assert.equal(orientation.hidden, true);
    b.emit('online');
    b.requests.at(-2).reply(status(null)); b.requests.at(-1).reply(full(null)); await b.flush();
    assert.equal(orientation.hidden, true);
    assert.equal(orientation.textContent, '');
});

test('companion clears stale chart readings and reports local archive and UPS faults', async () => {
    const b = browser('companion');
    const payload = full(null);
    const metric = {id: 'sensor_user_35', label: 'Lux', unit: 'lx'};
    Object.assign(payload, {metrics: [metric], defaults: [metric.id],
        series: [{...metric, points: [['2026-11-07T20:59:00+01:00', 2], ['2026-11-07T21:00:00+01:00', null]]}]});
    b.requests[0].reply({...status(null), archive: 'mount', ups_unreadable: true});
    b.requests[1].reply(payload);
    await b.flush();
    assert.equal(b.el('chart-slot-1.chart-value').textContent, '–');
    assert.match(b.el('connection-message').textContent, /Cannot read UPS status/);
    assert.match(b.el('connection-message').textContent, /Archive is not mounted/);
    b.emit('online');
    payload.series[0].points.push(['2026-11-07T21:01:00+01:00', 0]);
    b.requests.at(-2).reply({...status(null), ups_unreadable: false});
    b.requests.at(-1).reply(payload);
    await b.flush();
    assert.equal(b.el('chart-slot-1.chart-value').textContent, '0 lx');
    assert.doesNotMatch(b.el('connection-message').textContent, /Cannot read UPS status|Archive is not mounted/);
});
