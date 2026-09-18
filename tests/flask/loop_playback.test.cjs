// Also run by test_loop_playback.py as part of the pytest suite.
// Run directly with: node --test tests/flask/loop_playback.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function player(template, frames, options = {}) {
    let now = 0;
    let timerId = 0;
    let active = 0;
    let peakActive = 0;
    const timers = new Map();
    const displayed = [];
    const requested = [];
    const resized = [];
    const cleared = [];
    const requests = [];
    const handlers = new Map();
    const values = { '#HISTORY_SELECT': '900' };
    const setTimeout = (callback, delay) => {
        const id = ++timerId;
        timers.set(id, { at: now + Number(delay), callback });
        return id;
    };
    const record = (src) => displayed.push({ src, at: now });
    class Image {
        constructor() {
            this.width = 1920;
            this.height = 1080;
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
            if (settings.hang) return;
            setTimeout(() => {
                if (!this.url) return;
                if (settings.error) {
                    this.onerror?.();
                } else {
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
        setAttribute(key, value) {
            resized.push(key);
            this[key] = value;
        },
        getContext: () => ({
            clearRect: (...args) => cleared.push(args),
            drawImage: (img) => record(img.src),
        }),
    };
    const $ = (selector) => ({
        ready() {},
        on: (event, handler) => handlers.set(`${selector}:${event}`, handler),
        val: () => values[selector],
        attr: ({ src }) => record(src),
        show() {}, hide() {}, html() {}, text() {},
    });
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
        window: { innerWidth: 800, innerHeight: 600 },
        document: { getElementById: () => canvas },
        console: { log() {} },
        $, localStorage: { setItem() {} },
    });
    const source = fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/templates', template), 'utf8');
    const script = source.match(/<script type="text\/javascript">([\s\S]*?)<\/script>/)[1]
        .replace(/\{\{[\s\S]*?\}\}/g, '0');
    vm.runInContext(script, context, { filename: template });
    vm.runInContext(source.match(/<script>([\s\S]*?)<\/script>/)[1], context);
    context.json_data.image_list = frames.map((url) => ({ url }));
    context.frame_delay_ms = 20;
    context.refreshInterval = 1000;
    context.history_seconds = '900';
    context.page_settings = {};
    context.rock = options.rock || false;
    const completion = context.loop();

    async function advance(milliseconds) {
        const target = now + milliseconds;
        // Let promises enqueue their timers before choosing the next deadline.
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
    function changeHistory(value) {
        values['#HISTORY_SELECT'] = value;
        handlers.get('#HISTORY_SELECT:change')();
    }
    function respond(index, urls) {
        requests[index].success({ image_list: urls.map((url) => ({ url })), message: urls.length ? '' : 'No Timelapse Data' });
    }
    const refresh = context.loadNextImage || context.loadImages;
    return { context, displayed, requested, resized, cleared, advance, completion,
        requests, changeHistory, respond, refresh,
        peakActive: () => peakActive };
}

for (const template of ['loop_img.html', 'loop_canvas.html']) {
    test(`${template}: buffers at most four frames and presents decoded frames in order at 50 FPS`, async () => {
        const p = player(template, ['h', 'g', 'f', 'e', 'd', 'c', 'b', 'a'], {
            loads: { a: { delay: 80, decodeDelay: 20 } },
        });
        assert.deepEqual(p.requested, ['a', 'b', 'c', 'd']);
        await p.advance(99);
        assert.deepEqual(p.displayed, []);
        await p.advance(201);
        assert.deepEqual(p.displayed.map((frame) => frame.src), ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']);
        assert.deepEqual(p.displayed.map((frame) => frame.at), [100, 120, 140, 160, 180, 200, 220, 240]);
        assert.ok(p.peakActive() <= 4);
        await p.completion;
    });

    test(`${template}: a slow frame holds the previous image without a catch-up burst`, async () => {
        const p = player(template, ['c', 'b', 'a'], { loads: { b: { delay: 120 } } });
        await p.advance(119);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 0 }]);
        await p.advance(61);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 0 }, { src: 'b', at: 120 }, { src: 'c', at: 140 }]);
        await p.completion;
    });

    for (const stalled of [{ hang: true }, { decodeDelay: 15010 }]) {
        test(`${template}: skips failed images and timeouts, ignoring late decode completion ${JSON.stringify(stalled)}`, async () => {
            const p = player(template, ['d', 'c', 'b', 'a'], {
                loads: { a: { error: true }, b: { decodeError: true }, c: stalled },
            });
            await p.advance(14999);
            assert.deepEqual(p.displayed, []);
            await p.advance(101);
            assert.deepEqual(p.displayed, [{ src: 'd', at: 15000 }]);
            await p.completion;
        });
    }

    test(`${template}: preserves Rock order and the three-second end pause`, async () => {
        const p = player(template, ['c', 'b', 'a'], { rock: true });
        await p.advance(3119);
        assert.deepEqual(p.displayed.map((frame) => frame.src), ['c', 'b', 'a', 'a', 'b', 'c']);
        await p.advance(1);
        assert.deepEqual(p.displayed.at(-1), { src: 'c', at: 3120 });
    });

    test(`${template}: speed changes affect the next frame delay`, async () => {
        const p = player(template, ['c', 'b', 'a']);
        await p.advance(10);
        p.context.frame_delay_ms = '100';
        await p.advance(210);
        assert.deepEqual(p.displayed.map((frame) => frame.at), [0, 20, 120]);
        await p.completion;
    });

    test(`${template}: routine refresh still takes effect at the existing loop boundary`, async () => {
        const p = player(template, ['b', 'a']);
        await p.advance(10);
        p.refresh();
        p.respond(0, ['new']);
        await p.advance(3030);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 0 }, { src: 'b', at: 20 }, { src: 'new', at: 3040 }]);
    });

    test(`${template}: history selection requests immediately and interrupts a sleeping pass`, async () => {
        const p = player(template, ['c', 'b', 'a']);
        await p.advance(10);
        p.changeHistory('1800');
        assert.equal(p.requests[0].data.limit_s, '1800');
        assert.equal(p.context.page_settings.history_seconds, '1800');
        p.respond(0, ['new']);
        await p.advance(100);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 0 }, { src: 'new', at: 10 }]);
    });

    test(`${template}: switching history cancels old loading and decoding frames`, async () => {
        const p = player(template, ['d', 'c', 'b', 'a'], {
            loads: { a: { hang: true }, b: { decodeDelay: 500 }, c: { hang: true }, d: { hang: true } },
        });
        await p.advance(10);
        p.changeHistory('1800');
        p.respond(0, ['new']);
        await p.advance(600);
        assert.deepEqual(p.displayed, [{ src: 'new', at: 10 }]);
        assert.ok(p.peakActive() <= 4);
    });

    test(`${template}: history change bypasses the endpoint pause without leaving a second loop`, async () => {
        const p = player(template, ['old']);
        await p.advance(100);
        p.changeHistory('1800');
        p.respond(0, ['new']);
        await p.advance(3020);
        assert.deepEqual(p.displayed, [{ src: 'old', at: 0 }, { src: 'new', at: 100 }, { src: 'new', at: 3120 }]);
    });

    test(`${template}: only the latest history response wins and refresh uses one timer`, async () => {
        const p = player(template, ['old']);
        p.refresh();
        await p.advance(10);
        p.changeHistory('1800');
        p.changeHistory('900');
        assert.equal(p.requests.length, 3);
        assert.ok(p.requests[0].aborted && p.requests[1].aborted);
        p.respond(1, ['obsolete']);
        p.respond(2, ['latest']);
        p.respond(0, ['also-obsolete']);
        await p.advance(999);
        assert.equal(p.requests.length, 3);
        assert.deepEqual(p.displayed, [{ src: 'old', at: 0 }, { src: 'latest', at: 10 }]);
        await p.advance(1);
        assert.equal(p.requests.length, 4);
        assert.equal(p.requests[3].data.limit_s, '900');
    });

    test(`${template}: failed history request keeps playback and retries the selected history`, async () => {
        const p = player(template, ['b', 'a']);
        await p.advance(10);
        p.changeHistory('1800');
        p.requests[0].error({ status: 503 });
        await p.advance(1000);
        assert.deepEqual(p.displayed.map((frame) => frame.src), ['a', 'b']);
        assert.equal(p.requests[1].data.limit_s, '1800');
        p.respond(1, ['new']);
        await p.advance(0);
        assert.deepEqual(p.displayed.at(-1), { src: 'new', at: 1010 });
    });

    test(`${template}: empty selected history holds the last frame and resumes on refresh`, async () => {
        const p = player(template, ['b', 'a']);
        await p.advance(10);
        p.changeHistory('1800');
        p.respond(0, []);
        await p.advance(1000);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 0 }]);
        p.respond(1, ['new']);
        await p.advance(100);
        assert.deepEqual(p.displayed.at(-1), { src: 'new', at: 1110 });
    });

    test(`${template}: waits for an empty list and supports browsers without decode`, async () => {
        const p = player(template, [], { noDecode: true });
        await p.advance(50);
        assert.deepEqual(p.requested, []);
        p.context.json_data.image_list = [{ url: 'a' }];
        await p.advance(70);
        assert.deepEqual(p.displayed, [{ src: 'a', at: 100 }]);
        await p.completion;
    });
}

test('canvas only resizes when needed and clears each frame', async () => {
    const p = player('loop_canvas.html', ['c', 'b', 'a']);
    await p.advance(20);
    assert.deepEqual(p.resized, ['width', 'height']);
    assert.equal(p.cleared.length, 2);
    p.context.window.innerWidth = 1000;
    await p.advance(40);
    assert.deepEqual(p.resized, ['width', 'height', 'width', 'height']);
    assert.deepEqual(p.cleared.at(-1), [0, 0, 1000, 600]);
    await p.completion;
});
