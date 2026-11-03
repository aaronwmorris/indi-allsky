// Tests for indi-allsky Configuration Live Search & Deep-Linking
// Run directly with: node --test tests/flask/config_search.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function createMockElement(id, tagName = 'div', options = {}) {
    const classListSet = new Set(options.classes || []);
    const attrs = new Map();
    const listeners = new Map();

    const el = {
        id: id || '',
        tagName: tagName.toUpperCase(),
        type: options.type || 'text',
        value: options.value || '',
        textContent: options.textContent || '',
        innerHTML: '',
        style: {},
        checked: !!options.checked,
        parentElement: options.parentElement || null,
        children: [],
        set className(val) {
            classListSet.clear();
            if (val) {
                val.split(/\s+/).forEach(c => { if (c) classListSet.add(c); });
            }
        },
        get className() {
            return Array.from(classListSet).join(' ');
        },
        classList: {
            add(...cls) { cls.forEach(c => classListSet.add(c)); },
            remove(...cls) { cls.forEach(c => classListSet.delete(c)); },
            toggle(c, force) {
                if (force === undefined) {
                    if (classListSet.has(c)) classListSet.delete(c);
                    else classListSet.add(c);
                } else if (force) {
                    classListSet.add(c);
                } else {
                    classListSet.delete(c);
                }
            },
            contains(c) { return classListSet.has(c); },
        },
        setAttribute(k, v) { attrs.set(k, String(v)); },
        getAttribute(k) { return attrs.get(k) || null; },
        removeAttribute(k) { attrs.delete(k); },
        hasAttribute(k) { return attrs.has(k); },
        addEventListener(evt, fn) {
            if (!listeners.has(evt)) listeners.set(evt, []);
            listeners.get(evt).push(fn);
        },
        removeEventListener(evt, fn) {
            if (!listeners.has(evt)) return;
            const arr = listeners.get(evt);
            const idx = arr.indexOf(fn);
            if (idx !== -1) arr.splice(idx, 1);
        },
        dispatchEvent(evt) {
            const handlers = listeners.get(evt.type) || [];
            handlers.forEach(h => h(evt));
        },
        appendChild(child) {
            el.children.push(child);
            child.parentElement = el;
            return child;
        },
        remove() {
            if (el.parentElement) {
                const idx = el.parentElement.children.indexOf(el);
                if (idx !== -1) el.parentElement.children.splice(idx, 1);
                el.parentElement = null;
            }
        },
        contains(target) {
            let cur = target;
            while (cur) {
                if (cur === el) return true;
                cur = cur.parentElement;
            }
            return false;
        },
        focus() { el.focused = true; },
        blur() { el.focused = false; },
        select() { el.selected = true; },
        scrollIntoView() { el.scrolledIntoView = true; },
        closest(selector) {
            let cur = el;
            while (cur) {
                if (matchesSelector(cur, selector)) return cur;
                cur = cur.parentElement;
            }
            return null;
        },
        querySelector(selector) {
            return findFirst(el, node => node !== el && matchesSelector(node, selector));
        },
        querySelectorAll(selector) {
            const results = [];
            findAll(el, node => {
                if (node !== el && matchesSelector(node, selector)) results.push(node);
            });
            return results;
        },
    };

    return el;
}

function matchesSelector(el, selector) {
    if (!el || !selector) return false;
    const parts = selector.split(',').map(s => s.trim());
    for (const part of parts) {
        if (part.includes('tw\\:font-bold') && el.classList.contains('tw:font-bold')) return true;
        if (part.includes('tw\\:tracking-widest') && el.classList.contains('tw:tracking-widest')) return true;
        if (part.includes('btn-enable-parent') && el.classList.contains('btn-enable-parent')) return true;
        if (part.startsWith('.') && el.classList.contains(part.slice(1).replace(/\\/g, ''))) return true;
        if (part === 'label' && el.tagName === 'LABEL') return true;
        if (part === 'span' && el.tagName === 'SPAN') return true;
        if (part === 'input[type="checkbox"]' && el.tagName === 'INPUT' && el.type === 'checkbox') return true;
        if (part.startsWith('label[for="')) {
            const id = part.slice(11, -2);
            if (el.tagName === 'LABEL' && el.getAttribute('for') === id) return true;
        }
        if (part.startsWith('[data-tab-target="')) {
            const tgt = part.slice(18, -2);
            if (el.getAttribute('data-tab-target') === tgt) return true;
        }
        if (part.startsWith('#')) {
            if (el.id === part.slice(1)) return true;
        }
    }
    return false;
}

function findFirst(root, predicate) {
    for (const child of root.children) {
        if (predicate(child)) return child;
        const deep = findFirst(child, predicate);
        if (deep) return deep;
    }
    return null;
}

function findAll(root, predicate) {
    for (const child of root.children) {
        if (predicate(child)) predicate(child);
        findAll(child, predicate);
    }
}

function buildMockDOM() {
    const docListeners = new Map();
    const elementRegistry = new Map();
    const indexedInputs = [];

    const root = createMockElement('root', 'div');

    const form = createMockElement('form_config', 'form', { classes: ['mode-simple'] });
    root.children.push(form);
    form.parentElement = root;
    elementRegistry.set('form_config', form);

    const searchWrapper = createMockElement('config-search-wrapper', 'div');
    const searchInput = createMockElement('config-search-input', 'input');
    const searchClear = createMockElement('config-search-clear', 'button');
    const searchDropdown = createMockElement('config-search-dropdown', 'div');
    searchDropdown.style.display = 'none';
    const searchResults = createMockElement('config-search-results', 'div');
    const searchCount = createMockElement('config-search-count', 'span');
    const searchTitle = createMockElement('config-search-header-title', 'span');

    searchDropdown.children.push(searchTitle, searchCount, searchResults);
    searchTitle.parentElement = searchDropdown;
    searchCount.parentElement = searchDropdown;
    searchResults.parentElement = searchDropdown;

    searchWrapper.children.push(searchInput, searchClear, searchDropdown);
    searchInput.parentElement = searchWrapper;
    searchClear.parentElement = searchWrapper;
    searchDropdown.parentElement = searchWrapper;

    form.children.push(searchWrapper);
    searchWrapper.parentElement = form;

    elementRegistry.set('config-search-wrapper', searchWrapper);
    elementRegistry.set('config-search-input', searchInput);
    elementRegistry.set('config-search-clear', searchClear);
    elementRegistry.set('config-search-dropdown', searchDropdown);
    elementRegistry.set('config-search-results', searchResults);
    elementRegistry.set('config-search-count', searchCount);
    elementRegistry.set('config-search-header-title', searchTitle);

    form.querySelectorAll = function(selector) {
        if (selector.includes('.tab-pane input[id]')) {
            return indexedInputs;
        }
        return root.querySelectorAll(selector);
    };

    // Tab pane 1: Camera
    const tabBtnCamera = createMockElement('nav-camera-tab', 'button', { textContent: 'Camera' });
    tabBtnCamera.setAttribute('data-tab-target', 'nav-camera');
    elementRegistry.set('nav-camera-tab', tabBtnCamera);

    const paneCamera = createMockElement('nav-camera', 'div', { classes: ['tab-pane'] });
    const cardCamera = createMockElement('card-camera', 'div', { classes: ['tw:card'] });
    elementRegistry.set('card-camera', cardCamera);
    const cardTitleCamera = createMockElement('', 'span', { classes: ['tw:font-bold', 'tw:uppercase'], textContent: 'Hardware' });
    cardCamera.children.push(cardTitleCamera);
    cardTitleCamera.parentElement = cardCamera;

    // Field 1: CAMERA_GAIN (numeric value 100)
    const rowCameraGain = createMockElement('row-camera-gain', 'div', { classes: ['tw:flex'] });
    const labelGain = createMockElement('', 'label', { textContent: 'Camera Gain' });
    labelGain.setAttribute('for', 'CAMERA_GAIN');
    const inputGain = createMockElement('CAMERA_GAIN', 'input', { value: '100' });
    const descGain = createMockElement('', 'span', { classes: ['tw:text-base-content/60'], textContent: 'Sensor analogue gain value' });
    rowCameraGain.children.push(labelGain, inputGain, descGain);
    labelGain.parentElement = rowCameraGain;
    inputGain.parentElement = rowCameraGain;
    descGain.parentElement = rowCameraGain;
    cardCamera.children.push(rowCameraGain);
    rowCameraGain.parentElement = cardCamera;
    indexedInputs.push(inputGain);
    elementRegistry.set('CAMERA_GAIN', inputGain);
    elementRegistry.set('row-camera-gain', rowCameraGain);

    // Suggested Field 1: CCD_EXPOSURE_MAX
    const rowExpMax = createMockElement('row-exp-max', 'div', { classes: ['tw:flex'] });
    const labelExpMax = createMockElement('', 'label', { textContent: 'Max Night Exposure' });
    labelExpMax.setAttribute('for', 'CCD_EXPOSURE_MAX');
    const inputExpMax = createMockElement('CCD_EXPOSURE_MAX', 'input', { value: '60' });
    rowExpMax.children.push(labelExpMax, inputExpMax);
    labelExpMax.parentElement = rowExpMax;
    inputExpMax.parentElement = rowExpMax;
    cardCamera.children.push(rowExpMax);
    rowExpMax.parentElement = cardCamera;
    indexedInputs.push(inputExpMax);
    elementRegistry.set('CCD_EXPOSURE_MAX', inputExpMax);

    // Suggested Field 2: CCD_CONFIG__NIGHT__GAIN
    const rowNightGain = createMockElement('row-night-gain', 'div', { classes: ['tw:flex'] });
    const labelNightGain = createMockElement('', 'label', { textContent: 'Night Analogue Gain' });
    labelNightGain.setAttribute('for', 'CCD_CONFIG__NIGHT__GAIN');
    const inputNightGain = createMockElement('CCD_CONFIG__NIGHT__GAIN', 'input', { value: '200' });
    rowNightGain.children.push(labelNightGain, inputNightGain);
    labelNightGain.parentElement = rowNightGain;
    inputNightGain.parentElement = rowNightGain;
    cardCamera.children.push(rowNightGain);
    rowNightGain.parentElement = cardCamera;
    indexedInputs.push(inputNightGain);
    elementRegistry.set('CCD_CONFIG__NIGHT__GAIN', inputNightGain);

    paneCamera.children.push(cardCamera);
    cardCamera.parentElement = paneCamera;
    form.children.push(paneCamera);
    paneCamera.parentElement = form;

    // Tab pane 2: Processing (Expert field inside accordion)
    const tabBtnProcessing = createMockElement('nav-processing-tab', 'button', { textContent: 'Processing' });
    tabBtnProcessing.setAttribute('data-tab-target', 'nav-processing');
    elementRegistry.set('nav-processing-tab', tabBtnProcessing);

    const paneProcessing = createMockElement('nav-processing', 'div', { classes: ['tab-pane'] });
    const collapseProcessing = createMockElement('collapse-adv', 'div', { classes: ['tw:collapse'] });
    const collapseCheckbox = createMockElement('collapse-cb', 'input', { type: 'checkbox', checked: false });
    collapseProcessing.children.push(collapseCheckbox);
    collapseCheckbox.parentElement = collapseProcessing;

    const rowExpertCurve = createMockElement('row-stretch-curve', 'div', { classes: ['tw:flex', 'config-expert'] });
    const labelCurve = createMockElement('', 'label', { textContent: 'Histogram Stretch Curve' });
    labelCurve.setAttribute('for', 'STRETCH_CURVE');
    const inputCurve = createMockElement('STRETCH_CURVE', 'input', { value: 'gamma' });
    const descCurve = createMockElement('', 'span', { classes: ['tw:text-base-content/60'], textContent: 'Mathematical curve used for non-linear stretch' });
    rowExpertCurve.children.push(labelCurve, inputCurve, descCurve);
    labelCurve.parentElement = rowExpertCurve;
    inputCurve.parentElement = rowExpertCurve;
    descCurve.parentElement = rowExpertCurve;

    collapseProcessing.children.push(rowExpertCurve);
    rowExpertCurve.parentElement = collapseProcessing;
    paneProcessing.children.push(collapseProcessing);
    collapseProcessing.parentElement = paneProcessing;
    form.children.push(paneProcessing);
    paneProcessing.parentElement = form;
    indexedInputs.push(inputCurve);
    elementRegistry.set('STRETCH_CURVE', inputCurve);
    elementRegistry.set('collapse-cb', collapseCheckbox);

    // Tab pane 3: MQTT (Master toggle + dependent setting)
    const tabBtnMqtt = createMockElement('nav-mqtt-tab', 'button', { textContent: 'MQTT' });
    tabBtnMqtt.setAttribute('data-tab-target', 'nav-mqtt');
    elementRegistry.set('nav-mqtt-tab', tabBtnMqtt);

    const paneMqtt = createMockElement('nav-mqtt', 'div', { classes: ['tab-pane'] });
    const cardMqtt = createMockElement('card-mqtt', 'div', { classes: ['tw:card'] });

    // Master toggle: MQTTPUBLISH__ENABLE (unchecked / OFF)
    const rowMqttEnable = createMockElement('row-mqtt-enable', 'div', { classes: ['tw:flex'] });
    const labelMqttEnable = createMockElement('', 'label', { textContent: 'Enable MQTT' });
    labelMqttEnable.setAttribute('for', 'MQTTPUBLISH__ENABLE');
    const inputMqttEnable = createMockElement('MQTTPUBLISH__ENABLE', 'input', { type: 'checkbox', checked: false });
    rowMqttEnable.children.push(labelMqttEnable, inputMqttEnable);
    labelMqttEnable.parentElement = rowMqttEnable;
    inputMqttEnable.parentElement = rowMqttEnable;
    cardMqtt.children.push(rowMqttEnable);
    rowMqttEnable.parentElement = cardMqtt;
    indexedInputs.push(inputMqttEnable);
    elementRegistry.set('MQTTPUBLISH__ENABLE', inputMqttEnable);
    elementRegistry.set('row-mqtt-enable', rowMqttEnable);

    // Dependent setting: MQTTPUBLISH__HOST
    const rowMqttHost = createMockElement('row-mqtt-host', 'div', { classes: ['tw:flex'] });
    const labelMqttHost = createMockElement('', 'label', { textContent: 'MQTT Broker Host' });
    labelMqttHost.setAttribute('for', 'MQTTPUBLISH__HOST');
    const inputMqttHost = createMockElement('MQTTPUBLISH__HOST', 'input', { value: 'mqtt.local' });
    rowMqttHost.children.push(labelMqttHost, inputMqttHost);
    labelMqttHost.parentElement = rowMqttHost;
    inputMqttHost.parentElement = rowMqttHost;
    cardMqtt.children.push(rowMqttHost);
    rowMqttHost.parentElement = cardMqtt;
    indexedInputs.push(inputMqttHost);
    elementRegistry.set('MQTTPUBLISH__HOST', inputMqttHost);
    elementRegistry.set('row-mqtt-host', rowMqttHost);

    paneMqtt.children.push(cardMqtt);
    cardMqtt.parentElement = paneMqtt;
    form.children.push(paneMqtt);
    paneMqtt.parentElement = form;

    // Mock Document & Window
    const document = {
        readyState: 'complete',
        createElement(tag) {
            return createMockElement('', tag);
        },
        getElementById(id) {
            return elementRegistry.get(id) || null;
        },
        querySelector(selector) {
            if (selector.startsWith('#')) return elementRegistry.get(selector.slice(1)) || null;
            if (selector === '[data-tab-target="nav-camera"]') return tabBtnCamera;
            if (selector === '[data-tab-target="nav-processing"]') return tabBtnProcessing;
            if (selector === '[data-tab-target="nav-mqtt"]') return tabBtnMqtt;
            return root.querySelector(selector);
        },
        querySelectorAll(selector) {
            return form.querySelectorAll(selector);
        },
        addEventListener(evt, fn) {
            if (!docListeners.has(evt)) docListeners.set(evt, []);
            docListeners.get(evt).push(fn);
        },
        removeEventListener(evt, fn) {
            if (!docListeners.has(evt)) return;
            const arr = docListeners.get(evt);
            const idx = arr.indexOf(fn);
            if (idx !== -1) arr.splice(idx, 1);
        },
        dispatchEvent(evt) {
            const handlers = [...(docListeners.get(evt.type) || [])];
            handlers.forEach(h => h(evt));
        },
        activeElement: null,
    };

    const tabsShown = [];
    const fieldsHighlighted = [];
    let currentMode = 'simple';

    const window = {
        indiAllskyTabs: {
            showTab(tab) { tabsShown.push(tab); return true; },
            highlightField(id) { fieldsHighlighted.push(id); },
        },
        setConfigMode(mode) {
            currentMode = mode;
            form.classList.remove('mode-simple', 'mode-expert');
            form.classList.add('mode-' + mode);
        },
        history: {
            replaceState(state, title, url) {
                window.location.hash = url;
            },
        },
        location: { hash: '' },
    };

    return {
        root,
        form,
        document,
        window,
        elements: elementRegistry,
        indexedInputs,
        tabsShown,
        fieldsHighlighted,
        getMode: () => currentMode,
    };
}

function loadConfigSearch(env) {
    const code = fs.readFileSync(path.join(__dirname, '../../indi_allsky/flask/static/js/indi-allsky-config-search.js'), 'utf8');
    const context = vm.createContext({
        document: env.document,
        window: env.window,
        history: env.window.history,
        setTimeout: (fn, delay) => {
            if (delay <= 300) {
                // simulate delayed execution for setup timers
                fn();
            }
            return 1;
        },
        clearTimeout: () => {},
        console,
    });
    vm.runInContext(code, context);
}

test('Config search indexes elements and renders live value badges', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const dropdown = env.elements.get('config-search-dropdown');
    const results = env.elements.get('config-search-results');

    assert.equal(dropdown.style.display, 'none');

    // Type query "gain"
    input.value = 'gain';
    input.dispatchEvent({ type: 'input' });

    // Dropdown visible with matching items and live value badge "100"
    assert.equal(dropdown.style.display, 'block');
    assert.ok(results.innerHTML.includes('Camera'));
    assert.ok(results.innerHTML.includes('100'));
    assert.ok(results.innerHTML.includes('Hardware'));
});

test('Empty search input focus displays suggested settings', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const dropdown = env.elements.get('config-search-dropdown');
    const results = env.elements.get('config-search-results');
    const title = env.elements.get('config-search-header-title');

    input.value = '';
    input.dispatchEvent({ type: 'focus' });

    assert.equal(dropdown.style.display, 'block');
    assert.equal(title.textContent, 'Suggested Settings');
    assert.ok(results.innerHTML.includes('Max Night Exposure'));
    assert.ok(results.innerHTML.includes('Night Analogue Gain'));
});

test('Selecting dependent setting flashes parent toggle and displays hint banner', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const rowMqttEnable = env.elements.get('row-mqtt-enable');
    const rowMqttHost = env.elements.get('row-mqtt-host');

    input.value = 'broker';
    input.dispatchEvent({ type: 'input' });

    // Select MQTT Broker Host
    input.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {} });

    // MQTT tab must be activated
    assert.ok(env.tabsShown.includes('mqtt'));
    assert.ok(env.fieldsHighlighted.includes('MQTTPUBLISH__HOST'));

    // Parent enable row should be flashing and have guidance hint
    assert.ok(rowMqttEnable.classList.contains('parent-toggle-flashing'));
    assert.ok(rowMqttEnable.querySelector('.parent-toggle-hint') !== null);

    // Target child row should also have guidance banner with Enable Now button
    assert.ok(rowMqttHost.querySelector('.parent-toggle-hint') !== null);
    const enableBtn = rowMqttHost.querySelector('.btn-enable-parent');
    assert.ok(enableBtn !== null);

    // Clicking anywhere ceases flashing
    env.document.dispatchEvent({ type: 'click' });
    assert.ok(!rowMqttEnable.classList.contains('parent-toggle-flashing'));
    assert.ok(rowMqttEnable.querySelector('.parent-toggle-hint') === null);
});

test('Clicking Enable Now on dependent setting turns on parent toggle', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const rowMqttEnable = env.elements.get('row-mqtt-enable');
    const rowMqttHost = env.elements.get('row-mqtt-host');
    const inputMqttEnable = env.elements.get('MQTTPUBLISH__ENABLE');

    assert.equal(inputMqttEnable.checked, false);

    input.value = 'broker';
    input.dispatchEvent({ type: 'input' });
    input.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {} });

    const enableBtn = rowMqttHost.querySelector('.btn-enable-parent');
    assert.ok(enableBtn !== null);

    enableBtn.dispatchEvent({ type: 'click', preventDefault() {}, stopPropagation() {} });

    // Master toggle is now checked
    assert.equal(inputMqttEnable.checked, true);
    // Flashing on parent row ceased
    assert.ok(!rowMqttEnable.classList.contains('parent-toggle-flashing'));
});

test('Dynamic re-indexing via window.reindexConfigSearch() detects added hardware', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const results = env.elements.get('config-search-results');

    // Dynamically insert new sensor field into DOM
    const rowNewSensor = createMockElement('row-bme280', 'div', { classes: ['tw:flex'] });
    const labelSensor = createMockElement('', 'label', { textContent: 'BME280 Calibration Offset' });
    labelSensor.setAttribute('for', 'TEMP_SENSOR__BME280_OFFSET');
    const inputSensor = createMockElement('TEMP_SENSOR__BME280_OFFSET', 'input', { value: '1.5' });
    rowNewSensor.children.push(labelSensor, inputSensor);
    labelSensor.parentElement = rowNewSensor;
    inputSensor.parentElement = rowNewSensor;

    const cardCamera = env.elements.get('card-camera');
    cardCamera.children.push(rowNewSensor);
    rowNewSensor.parentElement = cardCamera;

    env.indexedInputs.push(inputSensor);
    env.elements.set('TEMP_SENSOR__BME280_OFFSET', inputSensor);

    // Trigger dynamic reindex
    env.window.reindexConfigSearch();

    // Query for newly added sensor
    input.value = 'bme280';
    input.dispatchEvent({ type: 'input' });

    assert.ok(results.innerHTML.includes('BME280'));
    assert.ok(results.innerHTML.includes('Calibration Offset'));
    assert.ok(results.innerHTML.includes('1.5'));
    assert.ok(results.innerHTML.includes('1.5'));
});

test('Keyboard navigation: ArrowDown, ArrowUp, and Enter selection', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const dropdown = env.elements.get('config-search-dropdown');

    input.value = 'gain';
    input.dispatchEvent({ type: 'input' });
    assert.equal(dropdown.style.display, 'block');

    input.dispatchEvent({ type: 'keydown', key: 'ArrowDown', preventDefault() {} });
    input.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {} });

    assert.equal(dropdown.style.display, 'none');
    assert.ok(env.tabsShown.length > 0);
    assert.ok(env.fieldsHighlighted.length > 0);
});

test('Selecting an expert setting auto-promotes view to expert mode', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    input.value = 'stretch';
    input.dispatchEvent({ type: 'input' });

    input.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {} });

    assert.equal(env.getMode(), 'expert');
    assert.ok(env.tabsShown.includes('processing'));
    const cb = env.elements.get('collapse-cb');
    assert.equal(cb.checked, true);
    assert.ok(env.fieldsHighlighted.includes('STRETCH_CURVE'));
});

test('Escape key closes search dropdown', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const dropdown = env.elements.get('config-search-dropdown');

    input.value = 'gain';
    input.dispatchEvent({ type: 'input' });
    assert.equal(dropdown.style.display, 'block');

    input.dispatchEvent({ type: 'keydown', key: 'Escape', preventDefault() {} });
    assert.equal(dropdown.style.display, 'none');
});

test('Clear button resets input and closes dropdown', () => {
    const env = buildMockDOM();
    loadConfigSearch(env);

    const input = env.elements.get('config-search-input');
    const clearBtn = env.elements.get('config-search-clear');
    const dropdown = env.elements.get('config-search-dropdown');

    input.value = 'gain';
    input.dispatchEvent({ type: 'input' });
    assert.equal(clearBtn.style.display, 'flex');

    clearBtn.dispatchEvent({ type: 'click', preventDefault() {} });
    assert.equal(input.value, '');
    assert.equal(dropdown.style.display, 'none');
    assert.equal(clearBtn.style.display, 'none');
});
