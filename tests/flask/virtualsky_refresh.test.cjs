const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {makeSky} = require('./virtualsky_harness.cjs');

// Execute the page's real refresh code with controllable image/network loads.
function page() {
    const html = fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/templates/virtualsky.html'), 'utf8');
    const controls = new Map(), requests = [], instances = [], images = [];
    const $ = selector => {
        if (!controls.has(selector)) controls.set(selector, {
            value: 0, checked: false, styles: {}, attributes: {}, handlers: {},
            val() { return this.value; }, prop() { return this.checked; },
            width() { return this.renderWidth; }, height() { return this.renderHeight; },
            css(value) { Object.assign(this.styles, value); return this; },
            attr(value) { Object.assign(this.attributes, value); return this; },
            html() {}, on(event, fn) { this.handlers[event] = fn; },
        });
        return controls.get(selector);
    };
    $.ajax = options => requests.push(options);
    const document = {hidden: false};
    const context = vm.createContext({$, document, Date, console: {log() {}}, setTimeout() {},
        VirtualSkyCalibration: {install() {}},
        Image: class {
            constructor() { this.naturalWidth = 2408; this.naturalHeight = 2348; images.push(this); }
        },
        S: {virtualsky(options) {
            const sky = makeSky({...options, id: ''});
            // No DOM canvas in this harness; preserve the real resize call contract.
            sky.resize = (w, h) => { sky.wide = w; sky.tall = h; };
            instances.push(sky);
            return sky;
        }},
    });
    vm.runInContext(html.match(/<script type="text\/javascript">([\s\S]*?)<\/script>/)[1]
        .replace(/{{[\s\S]*?}}/g, '0'), context);
    vm.runInContext(html.match(/function forceRedrawPlanetarium\(\) {[\s\S]*?\n}/)[0], context);
    vm.runInContext(html.match(/\$\(document\)\.on\('visibilitychange'[\s\S]*?\n}\);/)[0], context);
    Object.assign(context, {camera_latitude: 53, camera_longitude: 11, camera_altitude: 87.42});
    for (const [key, value] of Object.entries({MAGNITUDE: 6, AZIMUTH_ANGLE: 359.6,
        POINTING_AZIMUTH: 177.04, IMAGE_CIRCLE_DIAMETER: 2211, OFFSET_X: -7, OFFSET_Y: -34})) {
        $('#'+key).value = value;
    }
    $('#SHOWSTARS').checked = true;
    $('#latest-image').renderWidth = 1204;
    $('#latest-image').renderHeight = 1174;
    const entry = {url: '/sky.jpg', timestamp: 1788731972, width: 2408, height: 2348};
    context.json_data.image_list = [entry];
    return {$, context, instances, images, requests, entry, document};
}

test('hundreds of unchanged gallery polls retain the same sky and canvas owner', async () => {
    const {context: c, instances, requests} = page();
    for (let i = 0; i < 300; i++) {
        c.loadJS('/images', {});
        requests.at(-1).success(c.json_data);
        await c.loop();
        c.img.onload();
    }
    assert.equal(instances.length, 1);
    assert.equal(c.last_image_timestamp, 1788731972);
    assert.equal(c.planetarium.showstars, true);
});

test('new frames and edited controls update the existing projection, clock and dimensions', async () => {
    const {$, context: c, instances, entry} = page();
    await c.loop(); c.img.onload();
    const before = c.planetarium.times.LST;
    entry.timestamp += 3600;
    // Actual pixels, rather than potentially stale server dimensions, set the scale.
    entry.width = 2500;
    await c.loop(); c.img.onload();
    assert.notEqual(c.planetarium.times.LST, before);
    assert.equal(c.planetarium.clock.getTime(), entry.timestamp*1000);
    $('#AZIMUTH_ANGLE').value = -3;
    $('#latest-image').renderWidth = 602;
    $('#latest-image').renderHeight = 587;
    c.forceRedrawPlanetarium(); c.img.onload();
    assert.equal(instances.length, 1);
    assert.equal(c.planetarium.az_off, -3);
    assert.equal(c.planetarium.wide, 2211/4);
    assert.equal(parseFloat($('#starmap').styles.left), (602-2211/4)/2-7/4);
    assert.equal(parseFloat($('#starmap').styles.top), (587-2211/4)/2+34/4);
});

test('returning to a visible tab redraws without solving and preserves temporary settings', async () => {
    const {$, context: c, instances, document} = page();
    await c.loop(); c.img.onload();
    $('#OFFSET_X').value = 12;
    $('#latest-image').renderWidth = 0;
    c.forceRedrawPlanetarium(); c.img.onload();
    assert.equal(c.redraw_planetarium, true);
    assert.equal(c.planetarium.wide, 1105.5);
    $('#latest-image').renderWidth = 1204;
    $(document).handlers.visibilitychange(); c.img.onload();
    assert.equal(c.redraw_planetarium, false);
    assert.equal(parseFloat($('#starmap').styles.left), (1204-1105.5)/2+6);
    assert.equal(instances.length, 1);
});

test('a late image cannot overwrite the current frame or its timestamp', async () => {
    const {context: c, images, entry} = page();
    await c.loop();
    c.json_data.image_list = [{...entry, timestamp: entry.timestamp+30, url: '/next.jpg'}];
    await c.loop(); c.img.onload();
    images[0].onload();
    assert.equal(c.last_image_timestamp, entry.timestamp+30);
    // A redraw can select another entry before the next polling timer fires.
    c.json_data.image_list = [{...entry, timestamp: entry.timestamp+60}];
    c.forceRedrawPlanetarium(); c.img.onload();
    assert.equal(c.last_image_timestamp, entry.timestamp+60);
});

test('a restored browser canvas schedules a redraw without another solve', async () => {
    const {$, context: c} = page();
    c.json_data.image_list = [];
    c.forceRedrawPlanetarium(); // startup can precede the first image
    c.json_data.image_list = [{url: '/sky.jpg', timestamp: 1788731972}];
    await c.loop(); c.img.onload();
    $('#starmap canvas').handlers.contextrestored();
    assert.notEqual(c.planetarium.pendingRefresh, undefined);
});
