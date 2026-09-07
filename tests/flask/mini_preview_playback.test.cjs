// Also run by test_mini_preview_playback.py as part of the pytest suite.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function player(sourceType, frames, options = {}) {
    let now = 0;
    let timerId = 0;
    let active = 0;
    let peakActive = 0;
    const timers = new Map();
    const displayed = [];
    const requested = [];
    const requests = [];
    const handlers = new Map();
    const values = {
        '#SOURCE_TYPE': sourceType, '#PRE_SECONDS_SELECT': '60',
        '#POST_SECONDS_SELECT': '60', '#FRAMERATE_SELECT': '50',
        '#PAN_MODE': 'static',
    };
    const setTimeout = (callback, delay) => {
        const id = ++timerId;
        timers.set(id, { at: now + Number(delay), callback });
        return id;
    };
    class Image {
        constructor() {
            this.naturalWidth = 1920;
            this.naturalHeight = 1080;
            this.complete = false;
            if (options.noDecode) this.decode = undefined;
        }
        set src(src) {
            this.url = src;
            if (!src) {
                this.release();
                return;
            }
            requested.push(src);
            this.pending = true;
            peakActive = Math.max(peakActive, ++active);
            const settings = options.loads?.[src] || {};
            this.naturalWidth = settings.width || 1920;
            if (settings.hang) return;
            setTimeout(() => {
                if (!this.url) return;
                if (settings.error) {
                    this.release();
                    this.onerror?.();
                } else {
                    this.complete = true;
                    if (options.noDecode) this.release();
                    this.onload?.();
                }
            }, settings.delay || 0);
        }
        get src() { return this.url; }
        release() {
            if (this.pending) active--;
            this.pending = false;
        }
        decode() {
            const settings = options.loads?.[this.src] || {};
            return new Promise((resolve, reject) => {
                setTimeout(() => {
                    this.release();
                    if (settings.decodeError) reject(new Error('Bad image'));
                    else resolve();
                }, settings.decodeDelay || 0);
            });
        }
    }
    const canvas = {
        width: 300, height: 150,
        getContext: () => ({
            clearRect() {},
            drawImage: (img, x, y, width, height) => displayed.push({
                src: img.src, at: now, x, y, width, height,
                progress: context.panorama_preview_progress,
                entry: context.panorama_preview_entry,
            }),
        }),
    };
    const $ = (selector) => {
        const element = {
            ready() {},
            on: (event, handler) => handlers.set(`${selector}:${event}`, handler),
            val(value) {
                if (value === undefined) return values[selector];
                values[selector] = value;
                return element;
            },
            attr(attributes) {
                if (selector === '#loop-image' && attributes.src) {
                    displayed.push({ src: attributes.src, at: now });
                }
                return element;
            },
        };
        for (const method of ['show', 'hide', 'html', 'text', 'empty', 'prop',
            'toggle', 'css', 'toggleClass', 'addClass', 'removeClass', 'appendTo']) {
            element[method] = () => element;
        }
        return element;
    };
    $.ajax = (settings) => {
        const request = { ...settings, aborted: false, abort() {
            this.aborted = true;
            settings.error({ status: 0 });
        } };
        requests.push(request);
        return request;
    };
    const context = vm.createContext({
        Image, AbortController, setTimeout, clearTimeout: (id) => timers.delete(id),
        document: { getElementById: (id) => id === 'panorama-output-preview' ? canvas : null },
        window: {}, $, console: { log() {} },
    });
    const source = fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/templates/mini_generate.html'), 'utf8');
    for (const script of source.matchAll(/<script(?: type="text\/javascript")?>([\s\S]*?)<\/script>/g)) {
        vm.runInContext(script[1].replace(/\{\{([\s\S]*?)\}\}/g, (_, expression) => {
            if (expression.trim() === 'panorama | tojson') {
                return JSON.stringify({ available: true, width: 1920, height: 1080 });
            }
            if (expression.trim() === 'source_type | tojson') return JSON.stringify(sourceType);
            return '0';
        }), context, { filename: 'mini_generate.html' });
    }
    const entries = (urls) => urls.map((url, index) => ({ url, timestamp: 100 + urls.length - index - 1 }));
    context.json_data.image_list = entries(frames);
    context.framerate = '50';
    context.history_seconds = 120;
    context.endDate_timestamp = 60;
    const completion = context.loop(context.preview_revision);

    async function advance(milliseconds) {
        const target = now + milliseconds;
        await new Promise(setImmediate);
        while (true) {
            const next = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
            if (!next || next[1].at > target) break;
            now = next[1].at;
            timers.delete(next[0]);
            next[1].callback();
            await new Promise(setImmediate);
        }
        now = target;
    }
    function change(selector, value) {
        values[selector] = value;
        handlers.get(`${selector}:change`)();
    }
    function respond(index, urls) {
        requests[index].success({ image_list: entries(urls), message: '' });
    }
    return { context, displayed, requested, requests, advance, change, respond,
        completion, values, canvas, peakActive: () => peakActive, active: () => active };
}

for (const sourceType of ['standard', 'panorama']) {
    test(`${sourceType}: decodes a bounded four-frame buffer and plays in order`, async () => {
        const p = player(sourceType, ['h', 'g', 'f', 'e', 'd', 'c', 'b', 'a'], {
            loads: { a: { delay: 80, decodeDelay: 20 } },
        });
        assert.deepEqual(p.requested, ['a', 'b', 'c', 'd']);
        await p.advance(99);
        assert.deepEqual(p.displayed, []);
        await p.advance(201);
        assert.deepEqual(p.displayed.map((f) => f.src), ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']);
        assert.deepEqual(p.displayed.map((f) => f.at), [100, 120, 140, 160, 180, 200, 220, 240]);
        assert.ok(p.peakActive() <= 4);
        await p.completion;
    });

    test(`${sourceType}: a slow frame holds the last image without a catch-up burst`, async () => {
        const p = player(sourceType, ['c', 'b', 'a'], { loads: { b: { delay: 120 } } });
        await p.advance(119);
        assert.deepEqual(p.displayed.map((f) => f.src), ['a']);
        await p.advance(61);
        assert.deepEqual(p.displayed.map((f) => f.src), ['a', 'b', 'c']);
        assert.deepEqual(p.displayed.map((f) => f.at), [0, 120, 140]);
        await p.completion;
    });

    for (const stalled of [{ hang: true }, { decodeDelay: 15010 }]) {
        test(`${sourceType}: skips load/decode failures and timeouts ${JSON.stringify(stalled)}`, async () => {
            const p = player(sourceType, ['d', 'c', 'b', 'a'], {
                loads: { a: { error: true }, b: { decodeError: true }, c: stalled },
            });
            await p.advance(14999);
            assert.deepEqual(p.displayed, []);
            await p.advance(101);
            assert.deepEqual(p.displayed.map((f) => f.src), ['d']);
            assert.equal(p.displayed[0].at, 15000);
            await p.completion;
        });
    }

    test(`${sourceType}: frame rate changes retain the three-second end pause`, async () => {
        const p = player(sourceType, ['c', 'b', 'a']);
        await p.advance(10);
        p.change('#FRAMERATE_SELECT', '10');
        await p.advance(3209);
        assert.deepEqual(p.displayed.map((f) => f.at), [0, 20, 120]);
        await p.advance(1);
        assert.equal(p.displayed.at(-1).src, 'a');
        assert.equal(p.displayed.at(-1).at, 3220);
    });

    for (const selector of ['#PRE_SECONDS_SELECT', '#POST_SECONDS_SELECT', '#SOURCE_TYPE']) {
        test(`${sourceType}: ${selector} cancels buffered loads and ignores stale results`, async () => {
            const p = player(sourceType, ['d', 'c', 'b', 'a'], {
                loads: { a: { hang: true }, b: { decodeDelay: 500 }, c: { hang: true }, d: { hang: true } },
            });
            p.context.loadImages();
            await p.advance(10);
            p.change(selector, selector === '#SOURCE_TYPE'
                ? (sourceType === 'standard' ? 'panorama' : 'standard') : '180');
            assert.equal(p.requests.length, 2);
            assert.equal(p.active(), 0);
            if (selector !== '#SOURCE_TYPE') assert.equal(p.requests[1].data.limit_s, 240);
            p.respond(1, ['new']);
            p.respond(0, ['obsolete']);
            await p.advance(600);
            assert.deepEqual(p.displayed.map((f) => f.src), ['new']);
            assert.ok(p.peakActive() <= 4);
            await p.completion;
        });
    }

    test(`${sourceType}: a selection change during the end pause starts only one new loop`, async () => {
        const p = player(sourceType, ['old']);
        await p.advance(100);
        p.change('#PRE_SECONDS_SELECT', '180');
        p.respond(0, ['new']);
        await p.advance(3120);
        assert.deepEqual(p.displayed.map((f) => f.src), ['old', 'new', 'new']);
        assert.deepEqual(p.displayed.map((f) => f.at), [0, 200, 3220]);
    });

    test(`${sourceType}: waits for an empty list and works without Image.decode`, async () => {
        const p = player(sourceType, [], { noDecode: true });
        await p.advance(50);
        assert.deepEqual(p.requested, []);
        p.context.json_data.image_list = [{ url: 'a' }];
        await p.advance(70);
        assert.deepEqual(p.displayed.map((f) => f.src), ['a']);
        assert.equal(p.displayed[0].at, 100);
        await p.completion;
    });
}

test('panorama preserves frame metadata for the crop and animated pan', async () => {
    const p = player('panorama', ['c', 'b', 'a'], { loads: { b: { delay: 120 } } });
    p.values['#PAN_MODE'] = 'linear';
    p.context.json_data.panorama_preflight = {
        start_reference: { timestamp: 100 }, end_reference: { timestamp: 102 },
    };
    p.context.panorama_start_selection = { x: 100, y: 20, width: 400, height: 200 };
    p.context.panorama_end_selection = { x: 300, y: 60, width: 400, height: 200 };
    await p.advance(180);
    assert.deepEqual(p.displayed.map((f) => [f.src, f.entry.url, f.progress, f.x, f.y]), [
        ['a', 'a', 0, 100, 20], ['b', 'b', 0.5, 200, 40], ['c', 'c', 1, 300, 60],
    ]);
    assert.ok(p.displayed.every((f) => f.width === 400 && f.height === 200));
    await p.completion;
});

test('panorama continues to reject frames with incompatible dimensions', async () => {
    const p = player('panorama', ['c', 'b', 'a'], { loads: { b: { width: 1000 } } });
    await p.advance(100);
    assert.deepEqual(p.displayed.map((f) => f.src), ['a', 'c']);
    await p.completion;
});
