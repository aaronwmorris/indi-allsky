const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function page() {
    const elements = new Map();
    const requests = [];
    const $ = (selector) => {
        if (!elements.has(selector)) elements.set(selector, { text: 'Loading...', style: {}, handlers: {} });
        const element = elements.get(selector);
        return {
            ready() {},
            text(value) { element.text = value; },
            css(value) { Object.assign(element.style, value); },
            on(event, handler) { element.handlers[event] = handler; },
        };
    };
    $.ajax = (settings) => requests.push(settings);
    const context = vm.createContext({ $, document: {}, console: { log() {} } });
    const template = fs.readFileSync(path.join(__dirname, '../../indi_allsky/flask/templates/support_info.html'), 'utf8');
    const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1]
        .replace(/\{\{ url_for\('indi_allsky\.([^']+)'\) \}\}/g, '/$1');
    vm.runInContext(script, context, { filename: 'support_info.html' });
    return { context, elements, requests };
}

test('successful support info preserves Unicode and enables downloads', () => {
    const p = page();
    p.context.loadSupportInfo();
    p.requests[0].success({ support_info: 'YouTube description: 🌌 Café' });
    assert.equal(p.elements.get('#support_info').text, 'YouTube description: 🌌 Café');
    assert.equal(p.elements.get('#loader_support').style.display, 'none');
    assert.equal(typeof p.elements.get('#dl_support').handlers.click, 'function');
});

test('failed generation replaces Loading and hides the spinner', () => {
    const p = page();
    p.context.loadSupportInfo();
    p.requests[0].error({ status: 400 });
    assert.match(p.elements.get('#support_info').text, /Unable to generate support info/);
    assert.match(p.elements.get('#support_info').text, /Webapp Log/);
    assert.equal(p.elements.get('#loader_support').style.display, 'none');
    assert.equal(p.elements.has('#dl_support'), false);
});

test('request errors still invoke the caller error callback', () => {
    const p = page();
    let status;
    p.context.loadJS('/support', null, (value) => { status = value; });
    p.requests[0].error({ status: 502 });
    assert.equal(status, 502);
    assert.equal(p.elements.get('#loader_support').style.display, 'none');
});
