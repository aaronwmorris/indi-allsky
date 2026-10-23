const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const templates = path.join(__dirname, '../../indi_allsky/flask/templates');
const methods = ['', 'gaussian_blur', 'median_blur', 'bilateral', 'wavelet'];

function page(template, night, day, useNightColor = false) {
    const source = fs.readFileSync(path.join(templates, template), 'utf8').replace(/\r\n/g, '\n');
    const elements = new Map();
    const handlers = new Map();
    function $(selector) {
        if (typeof selector !== 'string') return selector;
        if (selector.includes(', ')) return selector.split(', ').map($).reduce((group, next) => group.add(next));
        if (!elements.has(selector)) elements.set(selector, {
            value: '', checked: false, disabled: false, visible: false,
            val(value) {
                if (value === undefined) return this.value;
                this.value = value;
                return this;
            },
            prop(name) { return this[name]; },
            attr(attrs) { Object.assign(this, attrs); return this; },
            removeAttr(names) {
                for (const name of names.split(' ')) this[name] = false;
                return this;
            },
            addClass() { return this; },
            removeClass() { return this; },
            add(other) {
                return {
                    attr(attrs) { this.items.forEach(item => item.attr(attrs)); return this; },
                    removeAttr(names) { this.items.forEach(item => item.removeAttr(names)); return this; },
                    addClass() { return this; },
                    removeClass() { return this; },
                    items: [this, other],
                };
            },
            toggle(visible) { this.visible = visible; return this; },
        });
        return elements.get(selector);
    }
    $('#IMAGE_DENOISE').value = night;
    $('#IMAGE_DENOISE_DAY').value = day;
    $('#USE_NIGHT_COLOR').checked = useNightColor;
    for (const suffix of ['', '_DAY']) {
        $('#BILATERAL_SIGMA_COLOR' + suffix).value = 17;
        $('#BILATERAL_SIGMA_SPACE' + suffix).value = 29;
        $('#IMAGE_DENOISE_STRENGTH' + suffix).value = 4;
    }
    const context = vm.createContext({ $ });
    for (const id of ['USE_NIGHT_COLOR', 'IMAGE_DENOISE', 'IMAGE_DENOISE_DAY']) {
        const match = source.match(new RegExp(
            "\\$\\('#" + id + "'\\)\\.on\\('change', function\\(\\) \\{([\\s\\S]*?)\\n\\}\\);"
        ));
        if (match) handlers.set(id, vm.runInContext('(function() {' + match[1] + '\n})', context));
    }
    const initial = template === 'config.html'
        ? source.match(/    \/\/ Night color settings\n([\s\S]*?)    \/\/ Night timelapse settings/)[1]
        : source.match(/    \/\/ Initial denoise state\n([\s\S]*?)\n    init\(\);/)[1];
    vm.runInContext(initial, context);
    return {
        $,
        change(id, value) {
            if (id === 'USE_NIGHT_COLOR') $('#' + id).checked = value;
            else $('#' + id).value = value;
            handlers.get(id).call($('#' + id));
        },
    };
}

for (const night of methods) {
    for (const day of methods) {
        for (const useNightColor of [false, true]) {
            test(`saved config: night=${night}, day=${day}, useNight=${useNightColor}`, () => {
                const p = page('config.html', night, day, useNightColor);
                assert.equal(p.$('#bilateral-settings').visible, night === 'bilateral');
                assert.equal(p.$('#bilateral-settings-day').visible, day === 'bilateral');
                assert.equal(p.$('#BILATERAL_SIGMA_COLOR').disabled, night !== 'bilateral');
                assert.equal(p.$('#BILATERAL_SIGMA_SPACE_DAY').disabled, day !== 'bilateral' || useNightColor);
                assert.equal(p.$('#IMAGE_DENOISE_STRENGTH').value, 4);
                assert.equal(p.$('#IMAGE_DENOISE_STRENGTH_DAY').value, 4);
            });
        }
    }
}

test('Day and Night changes are independent and retain bilateral values', () => {
    const p = page('config.html', '', '');
    for (const suffix of ['', '_DAY']) {
        const row = suffix ? '#bilateral-settings-day' : '#bilateral-settings';
        const otherRow = suffix ? '#bilateral-settings' : '#bilateral-settings-day';
        for (const method of ['bilateral', 'wavelet', '', 'gaussian_blur', 'median_blur', 'bilateral']) {
            p.change('IMAGE_DENOISE' + suffix, method);
            assert.equal(p.$(row).visible, method === 'bilateral');
            assert.equal(p.$(otherRow).visible, suffix === '_DAY');
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR' + suffix).disabled, method !== 'bilateral');
            assert.equal(p.$('#BILATERAL_SIGMA_SPACE' + suffix).value, 29);
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR' + suffix).value, 17);
        }
    }
});

test('Use Night Color preserves Day visibility, values, and enablement rules', () => {
    for (const method of methods) {
        const p = page('config.html', 'wavelet', method);
        for (const checked of [true, false, true, false]) {
            p.change('USE_NIGHT_COLOR', checked);
            assert.equal(p.$('#bilateral-settings-day').visible, method === 'bilateral');
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR_DAY').disabled, checked || method !== 'bilateral');
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR_DAY').value, 17);
            assert.equal(p.$('#bilateral-settings').visible, false);
        }
    }
});

for (const method of methods) {
    test(`image processing initial selection and changes: ${method}`, () => {
        const p = page('imageprocessing.html', method, '');
        assert.equal(p.$('#bilateral-settings').visible, method === 'bilateral');
        assert.equal(p.$('#BILATERAL_SIGMA_COLOR').disabled, method !== 'bilateral');
        for (const next of ['bilateral', 'wavelet', '', 'gaussian_blur', 'median_blur', 'bilateral']) {
            p.change('IMAGE_DENOISE', next);
            assert.equal(p.$('#bilateral-settings').visible, next === 'bilateral');
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR').disabled, next !== 'bilateral');
            assert.equal(p.$('#BILATERAL_SIGMA_COLOR').value, 17);
            assert.equal(p.$('#BILATERAL_SIGMA_SPACE').value, 29);
        }
    });
}
