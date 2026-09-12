const assert = require('node:assert/strict');
const {test} = require('node:test');
const {makeSky} = require('./virtualsky_harness.cjs');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const rad = Math.PI / 180;
const close = (a, b, tolerance = 1e-8) => assert.ok(Math.abs(a-b) < tolerance, `${a} != ${b}`);

for (const asset of ['virtualsky.js', 'virtualsky.min.js']) {
    test(`${asset}: invalid lens curvature cannot replace a working projection`, () => {
        const sky = makeSky({fisheye_radial: 0.08}, asset);
        for (const value of [null, '0.1', NaN, Infinity, -0.51, 1.01]) {
            sky.init({fisheye_radial: value});
            assert.equal(sky.fisheye_radial, 0.08);
        }
    });
    test(`${asset}: catalogue precession preserves solar-system rendering and lookup`, () => {
        const sky = makeSky();
        const date = sky.horizon2coord([1, 0.3]);
        sky.ctx = {};
        sky.showplanets = true;
        sky.planets = [['test', 'white', [sky.times.JD-1, date.ra/rad, date.dec/rad, 0,
            sky.times.JD+1, date.ra/rad, date.dec/rad, 0]]];
        const drawn = [];
        sky.drawPlanet = (x,y,r,colour,label) => drawn.push([x,y,label]);
        sky.drawPlanets();
        const expected = drawn.splice(0);
        sky.precession = true;
        sky.drawPlanets();
        assert.deepEqual(drawn, expected);
        const [x,y] = drawn.find(p => p[2] === 'test');
        sky.lookup = {planet: sky.lookup.planet};
        const nearest = sky.nearestObject(x,y);
        assert.equal(nearest.type, 'planet');
        assert.ok(nearest.distance < 1e-4);
    });

    test(`${asset}: zenith retains the original projection exactly`, () => {
        for (const altitude of [undefined, null, 90]) {
            const sky = makeSky({fisheye_altitude: altitude, fisheye_azimuth: 213}, asset);
            for (const el of [-0.2, 0, 0.5, Math.PI/2]) {
                for (const az of [0, 1, 3, 6]) {
                    const p = sky.azel2xy(az, el, 1000, 1000);
                    const r = 500*Math.sin((Math.PI/2-el)/2)/0.70710678;
                    assert.equal(p.x, 500-r*Math.sin(az));
                    assert.equal(p.y, 500-r*Math.cos(az));
                    assert.equal(p.el, el);
                }
            }
        }
    });

    test(`${asset}: lens axis is centered regardless of heading and roll`, () => {
        for (const altitude of [0, 20, 54, 89.99]) {
            for (const heading of [0, 90, 213, 359]) {
                const sky = makeSky({fisheye_altitude: altitude, fisheye_azimuth: heading, az: 20}, asset);
                const p = sky.azel2xy((heading-sky.az_off)*rad, altitude*rad, 1000, 1000);
                close(p.x, 500);
                close(p.y, 500);
                // Visibility is still based on the real horizon.
                close(p.el, altitude*rad);
            }
        }
    });

    test(`${asset}: inverse coordinates and horizon clipping follow the tilted lens`, () => {
        const sky = makeSky({fisheye_altitude: 54, fisheye_azimuth: 35, az: 20}, asset);
        for (const [az, alt] of [[35, 54], [10, 20], [120, 50], [200, 70]]) {
            const p = sky.azel2xy(az*rad-sky.az_off*rad, alt*rad, 1000, 1000);
            const recovered = sky.xy2radec(p.x, p.y);
            const expected = sky.horizon2coord([alt*rad, az*rad]);
            close(Math.cos(recovered.ra), Math.cos(expected.ra));
            close(Math.sin(recovered.ra), Math.sin(expected.ra));
            close(recovered.dec, expected.dec);
        }
        const behind = sky.azel2xy((215-sky.az_off)*rad, 10*rad, 1000, 1000);
        assert.ok(Number.isNaN(behind.x));
        const below = sky.azel2xy((35-sky.az_off)*rad, -5*rad, 1000, 1000);
        assert.ok(Number.isFinite(below.x));
        assert.equal(sky.isVisible(below.el), false);
        assert.equal(sky.xy2radec(-100, -100), undefined);
    });

    test(`${asset}: cardinal labels follow the horizon or stay at the lens rim`, () => {
        const sky = makeSky({fisheye_altitude: 54, fisheye_azimuth: 0}, asset);
        const labels = [];
        sky.ctx = {beginPath() {}, fill() {}, fillText: (...args) => labels.push(args),
            measureText: () => ({width: 10})};
        sky.fontsize = () => 10;
        sky.getPhrase = value => value;
        sky.drawCardinalPoints();
        assert.ok(labels.some(([label]) => label === 'N'));
        assert.equal(labels.length, 4);
        const north = labels.find(([label]) => label === 'N');
        const p = sky.azel2xy(0, 0, 1000, 1000);
        close(north[2], p.y);
    });

    test(`${asset}: all direction labels survive slight tilt, arbitrary roll and small screens`, () => {
        for (const size of [240, 1000, 2211]) for (const heading of [0, 177.04, 270]) {
            for (const rotation of [-3, 0, 37, 359.6]) {
                const sky = makeSky({width: size, height: size, fisheye_altitude: 87.42,
                    fisheye_azimuth: heading, az: 180+rotation}, asset);
                const labels = [];
                sky.ctx = {beginPath() {}, fill() {}, fillText: (...args) => labels.push(args),
                    measureText: () => ({width: 10})};
                sky.fontsize = () => 10;
                sky.getPhrase = value => value;
                sky.drawCardinalPoints();
                assert.equal(labels.length, 4);
                for (const [, x, y] of labels) {
                    assert.ok(x >= 0 && x+10 <= size && y >= 10 && y <= size);
                    assert.ok(Math.hypot(x+5-size/2, y-size/2) <= size/2-9.99);
                }
            }
        }
    });
}

function calibrationPage() {
    const html = fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/templates/virtualsky.html'), 'utf8');
    const controls = new Map();
    const $ = id => {
        if (!controls.has(id)) controls.set(id, {
            handlers: {}, value: '0', properties: {},
            on(event, fn) { this.handlers[event] = fn; return this; },
            val(value) { if (value === undefined) return this.value; this.value = value; return this; },
            prop(key, value) { if (value === undefined) return this.properties[key]; this.properties[key] = value; return this; },
            addClass() { return this; }, removeClass() { return this; },
            text(value) { this.value = value; return this; }, show() { return this; }, hide() { return this; },
        });
        return controls.get(id);
    };
    const requests = [];
    $.ajax = options => requests.push(options);
    $('#lens_save').prop('disabled', /\sdisabled(?:\s|=|>)/.test(html.match(/<button id="lens_save"[^>]*>/)[0]));
    $('#LATITUDE_OFFSET').val('43.49');
    $('#POINTING_AZIMUTH').val('123');
    const context = vm.createContext({$, camera_id: 1, camera_altitude: 90, lensCalibration: null, calibrationMessage: '',
        precession: false, last_image_timestamp: 1770000000,
        forceRedrawPlanetarium() {}});
    vm.runInContext(html.slice(html.indexOf('const SOLVE_FIELDS')).split('</script>')[0], context);
    return {$, requests, context};
}

test('manual Save is available without solving and sends pointing and large offsets', () => {
    const {$, requests} = calibrationPage();
    assert.equal($('#lens_save').prop('disabled'), false);
    $('#lens_save').handlers.click();
    const payload = JSON.parse(requests[0].data);
    assert.equal(payload.action, 'save');
    assert.equal(payload.PRECESSION, false);
    assert.equal(payload.LATITUDE_OFFSET, '43.49');
    assert.equal(payload.POINTING_AZIMUTH, '123');
    assert.equal($('#lens_solve').prop('disabled'), true);
    requests[0].error({responseJSON: {message: 'Save failed'}});
    requests[0].complete();
    assert.equal($('#lens_save').prop('disabled'), false);
    assert.equal($('#lens_solve').prop('disabled'), false);
});

test('successful requests restore both buttons and keep the heading used by the solve', () => {
    const {$, requests} = calibrationPage();
    const values = {AZIMUTH_ANGLE: 200, LATITUDE_OFFSET: 0, LONGITUDE_OFFSET: 0,
        IMAGE_CIRCLE_DIAMETER: 2951, OFFSET_X: 7, OFFSET_Y: -135};
    $('#lens_solve').handlers.click();
    $('#POINTING_AZIMUTH').val('250');  // edited while the request is pending
    requests[0].success({success: true, values, message: 'Solved'});
    requests[0].complete();
    assert.equal($('#POINTING_AZIMUTH').val(), '123');
    for (const [field, value] of Object.entries(values)) {
        assert.equal($('#'+field).val(), value);
    }
    assert.equal($('#lens_save').prop('disabled'), false);
    assert.equal($('#lens_solve').prop('disabled'), false);

    $('#lens_save').handlers.click();
    requests[1].success({success: true, message: 'Saved'});
    requests[1].complete();
    assert.equal($('#lens_save').prop('disabled'), false);
    assert.equal($('#lens_solve').prop('disabled'), false);
});

test('unsuccessful solves restore manual Save after application and network failures', () => {
    for (const failure of ['success', 'error']) {
        const {$, requests, context} = calibrationPage();
        $('#lens_solve').handlers.click();
        assert.equal($('#lens_save').prop('disabled'), true);
        requests[0][failure]({success: false, message: 'No stars'});
        requests[0].complete();
        assert.equal($('#lens_save').prop('disabled'), false);
        assert.equal($('#LATITUDE_OFFSET').val(), '43.49');
        assert.equal(context.precession, false);
    }
});

test('recovered pointing updates the overlay, displayed altitude and next Save/Solve payload', () => {
    const {$, requests, context} = calibrationPage();
    const values = {AZIMUTH_ANGLE: 200, LATITUDE_OFFSET: 0, LONGITUDE_OFFSET: 0,
        IMAGE_CIRCLE_DIAMETER: 2951, OFFSET_X: 7, OFFSET_Y: -135,
        LENS_ALTITUDE: 0, POINTING_AZIMUTH: 0, PRECESSION: true, RADIAL_DISTORTION: 0.08};
    $('#lens_solve').handlers.click();
    assert.equal(JSON.parse(requests[0].data).PRECESSION, true);
    assert.equal(context.precession, false);
    requests[0].success({success: true, values, message: 'Pointing recovered'});
    requests[0].complete();
    assert.equal(context.camera_altitude, 0);
    assert.equal(context.precession, true);
    assert.equal($('#lens_altitude').value, 0);
    assert.equal($('#POINTING_AZIMUTH').val(), 0);
    assert.deepEqual(Array.from(context.calibrationGeometry()),
        [200, 0, 0, 2951, 7, -135, 0, 0, 0.08, 1]);
    for (const button of ['#lens_save', '#lens_solve']) {
        $(button).handlers.click();
        const payload = JSON.parse(requests.at(-1).data);
        for (const [field, value] of Object.entries(values)) assert.equal(payload[field], value);
        requests.at(-1).complete();
    }
});

test('declined calibration keeps the requested switch and explains why toggling has no effect', () => {
    const {$, requests} = calibrationPage();
    const values = {AZIMUTH_ANGLE: 200, LATITUDE_OFFSET: 0, LONGITUDE_OFFSET: 0,
        IMAGE_CIRCLE_DIAMETER: 2951, OFFSET_X: 7, OFFSET_Y: -135};
    $('#CALIBRATION_ENABLED').prop('checked', true);
    $('#lens_solve').handlers.click();
    requests[0].success({success: true, values, calibration: null,
        calibration_message: 'Too few reliable stars.', message: 'Geometry solved.'});
    requests[0].complete();
    assert.equal($('#CALIBRATION_ENABLED').prop('checked'), true);
    assert.equal($('#calibration_summary').value, 'No additional correction applied. Too few reliable stars.');
    for (const enabled of [false, true]) {
        $('#CALIBRATION_ENABLED').prop('checked', enabled);
        $('#CALIBRATION_ENABLED').handlers.change();
        assert.equal($('#calibration_summary').value, 'No additional correction applied. Too few reliable stars.');
    }
    $('#lens_solve').handlers.click();
    assert.equal(JSON.parse(requests[1].data).CALIBRATION_ENABLED, true);
    requests[1].success({success: true, values,
        calibration: {summary: 'Validated on unused stars.'}, message: 'Solved.'});
    requests[1].complete();
    assert.equal($('#calibration_summary').value, 'Additional correction enabled. Validated on unused stars.');
    $('#CALIBRATION_ENABLED').prop('checked', false);
    $('#CALIBRATION_ENABLED').handlers.change();
    assert.equal($('#calibration_summary').value, 'Additional correction off. Validated on unused stars.');
});
