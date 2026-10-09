const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {makeSky: makeVirtualSky} = require('./virtualsky_harness.cjs');

function makeSky(options = {}, asset = 'virtualsky.js') {
    return makeVirtualSky({latitude: 40.1, longitude: -75.4, az: 217.5, ...options}, asset);
}

function near(a, b) { assert.ok(Math.abs(a-b) < 1e-8, `${a} != ${b}`); }

for (const asset of ['virtualsky.js', 'virtualsky.min.js']) {
    for (const flip_h of [false, true]) for (const flip_v of [false, true]) {
        test(`${asset}: orientation ${flip_h}/${flip_v}, forward/inverse and resizing`, () => {
            const sky = makeSky({flip_h, flip_v}, asset);
            const plain = makeSky({}, asset);
            for (const size of [500, 1700]) {
                sky.wide = sky.tall = plain.wide = plain.tall = size;
                for (const [az, el] of [[0.1, 0.3], [1.7, 1.1], [5.2, 0.7]]) {
                    const coords = sky.horizon2coord([el, az]);
                    const p = sky.radec2xy(coords.ra, coords.dec);
                    const q = plain.radec2xy(coords.ra, coords.dec);
                    near(p.x, flip_h ? size-q.x : q.x);
                    near(p.y, flip_v ? size-q.y : q.y);
                    const inverse = sky.xy2radec(p.x, p.y);
                    near(inverse.ra, coords.ra);
                    near(inverse.dec, coords.dec);
                    sky.pointers = [];
                    sky.lang.starnames = {Target: 'Target'};
                    sky.lookup = {star: [{ra: coords.ra, dec: coords.dec, label: 'Target'}]};
                    assert.equal(sky.nearestObject(p.x, p.y).label, 'Target');
                }
                assert.equal(sky.xy2radec(-size, -size), undefined);
            }
        });

        test(`${asset}: orientation ${flip_h}/${flip_v}, readable labels`, () => {
            const sky = makeSky({flip_h, flip_v}, asset);
            const plain = makeSky({}, asset);
            function labels(s) {
                const calls = [];
                // No canvas reflection is available: glyphs must be drawn normally.
                s.ctx = {beginPath() {}, fill() {}, moveTo() {}, arc() {},
                    measureText: () => ({width: 10}), fillText: (...args) => calls.push(args)};
                s.fontsize = () => 10;
                s.getPhrase = text => text;
                s.drawCardinalPoints();
                return calls;
            }
            const baseline = labels(plain), flipped = labels(sky);
            assert.deepEqual(flipped.map(p => p[0]), ['N', 'E', 'S', 'W']);
            flipped.forEach((p, i) => {
                near(p[1]+5, flip_h ? 1000-(baseline[i][1]+5) : baseline[i][1]+5);
                near(p[2]-5, flip_v ? 1000-(baseline[i][2]-5) : baseline[i][2]-5);
            });
            const coords = sky.horizon2coord([0.7, 1.2]);
            const p = sky.radec2xy(coords.ra, coords.dec);
            const calls = [];
            sky.ctx.fillText = (...args) => calls.push(args);
            sky.showstarlabels = true;
            sky.stars = [[7, 2, coords.ra, coords.dec]];
            sky.starnames = {7: 'Readable star'};
            sky.htmlDecode = text => text;
            sky.drawStars();
            assert.equal(calls[0][0], 'Readable star');
            assert.ok(Math.abs(calls[0][1]-p.x) < 20);
            assert.ok(Math.abs(calls[0][2]-p.y) < 10);
        });
    }
    test(`${asset}: other projections keep their orientation`, () => {
        const plain = makeSky({projection: 'polar'}, asset);
        const flipped = makeSky({projection: 'polar', flip_h: true, flip_v: true}, asset);
        const p = plain.azel2xy(1, 0.5, 1000, 1000), q = flipped.azel2xy(1, 0.5, 1000, 1000);
        near(p.x, q.x); near(p.y, q.y);
    });
}

test('Solve and Save send checkbox booleans, including unchecked values', () => {
    const source = fs.readFileSync(path.join(__dirname, '../../../indi_allsky/flask/templates/virtualsky.html'), 'utf8');
    const script = source.slice(source.indexOf('const SOLVE_FIELDS'), source.indexOf('// Outcome-conditional'));
    for (const h of [false, true]) for (const v of [false, true]) {
        const context = vm.createContext({camera_id: 7, camera_altitude: 54, precession: true, lensCalibration: null, $: selector => ({
            on() {}, val: () => '25', prop: key => { assert.equal(key, 'checked'); return selector === '#FLIP_H' ? h : v; }
        })});
        vm.runInContext(script, context);
        for (const action of ['solve', 'save']) {
            const result = context.solverPayload(action);
            assert.equal(result.FLIP_H, h); assert.equal(result.FLIP_V, v);
        }
    }
});

test('Solve replaces manual flip settings with the detected orientation before drawing', () => {
    const source = fs.readFileSync(path.join(__dirname, '../../../indi_allsky/flask/templates/virtualsky.html'), 'utf8');
    const solve = source.slice(source.indexOf("$('#lens_solve').on('click'"));
    const callback = solve.slice(solve.indexOf('success: function(rdata)'), solve.indexOf('        error: function(xhr)'));
    for (const h of [false, true]) for (const v of [false, true]) {
        const fields = {'#FLIP_H': !h, '#FLIP_V': !v};
        let redraws = 0;
        const context = vm.createContext({SOLVE_FIELDS: ['AZIMUTH_ANGLE'], payload: {POINTING_AZIMUTH: 123}, updateCalibrationStatus() {}, $: selector => ({
            val: value => { fields[selector] = value; },
            prop: (key, value) => { fields[selector] = value; }
        }), setSolverMessage() {}, setSaveButtonFailed() {}, forceRedrawPlanetarium() {
            assert.equal(fields['#FLIP_H'], h); assert.equal(fields['#FLIP_V'], v); redraws++;
        }});
        vm.runInContext(`var handlers = {${callback}};`, context);
        context.handlers.success({success: true, values: {AZIMUTH_ANGLE: 75, FLIP_H: h, FLIP_V: v}});
        assert.equal(redraws, 1);
        assert.equal(fields['#AZIMUTH_ANGLE'], 75);
    }
});


test('alignment changes discard corrections before a single redraw and Save', () => {
    const source = fs.readFileSync(path.join(__dirname, '../../../indi_allsky/flask/templates/virtualsky.html'), 'utf8');
    // Include all event registrations so an earlier redraw cannot use a stale correction.
    const script = source.slice(source.indexOf('function forceRedrawPlanetarium'), source.indexOf('// Outcome-conditional'));
    const changes = [];
    let redraws = 0;
    const context = vm.createContext({window: {}, document: {}, img: {}, json_data: {image_list: [{}]},
        camera_id: 7, camera_altitude: 54, precession: true, lensCalibration: null,
        showImage() {
            assert.equal(context.lensCalibration, null);
            redraws++;
        },
        $: selector => ({
            on: (event, callback) => {
                if (event === 'change') changes.push({selector, callback});
            },
            ready() {}, text() {}, val() {return '25';}, prop() {return true;}
        })});
    vm.runInContext(script, context);
    for (const key of ['#FLIP_H', '#FLIP_V', '#AZIMUTH_ANGLE', '#POINTING_AZIMUTH',
        '#LATITUDE_OFFSET', '#LONGITUDE_OFFSET', '#IMAGE_CIRCLE_DIAMETER',
        '#OFFSET_X', '#OFFSET_Y', '#RADIAL_DISTORTION']) {
        context.lensCalibration = {summary: 'Old correction'};
        redraws = 0;
        changes.filter(c => c.selector.split(', ').includes(key)).forEach(c => c.callback());
        assert.equal(redraws, 1, key);
        assert.equal(context.lensCalibration, null);
        assert.equal(context.solverPayload('save').CALIBRATION, null);
    }
});
