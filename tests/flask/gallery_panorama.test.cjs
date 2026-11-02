const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function gallery(panoramas) {
    const template = fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/templates/gallery.html'), 'utf8');
    const start = template.indexOf('function populate_gallery(');
    const source = template.slice(start, template.indexOf('\nfunction ', start + 1))
        .replace(/{{\s*url_for\('indi_allsky\.([^']+)'\)\s*}}/g, '/$1');
    const anchors = [], controls = {}, listeners = {};
    const pswp = {
        options: {}, currIndex: 0,
        contentLoader: { destroy() {} },
        on(name, callback) { (listeners[name] ||= []).push(callback); },
        dispatch(name) { (listeners[name] || []).forEach(callback => callback()); },
        getNumItems() { return this.options.dataSource.length; },
        goTo(index) {
            this.currIndex = Math.max(0, Math.min(index, this.getNumItems() - 1));
            const item = this.options.dataSource[this.currIndex];
            this.currSlide = { data: item.getAttribute ? {element: item, src: item.getAttribute('href')} : item };
            this.dispatch('change');
        },
        refreshSlideContent(index) {
            assert.ok(this.options.dataSource[this.currIndex], 'current slide must remain valid');
            if (index === this.currIndex) this.goTo(index);
        },
        ui: { registerElement(options) {
            const element = { style: {}, setAttribute(key, value) { this[key] = value; } };
            controls[options.name] = { options, element };
            options.onInit?.(element, pswp);
        } },
    };
    const context = {
        lightbox: null, asi676mc_repair_gallery_enabled: false,
        scrollToTop() {}, PhotoSwipe: {},
        $(selector, attributes = {}) {
            const element = { getAttribute(key) { return String(attributes[key] ?? ''); } };
            if (selector === '<a />') anchors.push(element);
            return { 0: element, empty() {}, appendTo() {} };
        },
        PhotoSwipeLightbox: class {
            constructor() { this.pswp = pswp; }
            on(name, callback) { if (name === 'uiRegister') this.register = callback; }
            init() { this.register(); }
        },
    };
    vm.runInNewContext(source, context);
    context.populate_gallery(panoramas.map((available, index) => ({
        id: index + 1, url: `image${index + 1}.jpg`, width: 800, height: 900,
        thumbnail_url: `thumb${index + 1}.jpg`, date: `Frame ${index + 1}`, ts: 100 + index,
        panorama_id: available ? index + 21 : null,
        panorama_url: available ? `panorama${index + 1}.jpg` : null,
        panorama_width: available ? 3200 : null, panorama_height: available ? 800 : null,
    })));
    pswp.options.dataSource = anchors.map(element => ({element, src: element.getAttribute('href')}));
    pswp.goTo(0);
    return { pswp, controls, anchors, toggle() {
        controls['panorama-button'].options.onClick({}, controls['panorama-button'].element, pswp);
    } };
}

test('switching skips missing panoramas, preserves the capture, and adapts toolbar links', () => {
    const { pswp, controls, anchors, toggle } = gallery([true, false, true, true]);
    pswp.goTo(2);
    toggle();
    assert.equal(pswp.getNumItems(), 3);
    assert.equal(pswp.currIndex, 1);
    assert.equal(pswp.currSlide.data.element, anchors[2]);
    assert.equal(pswp.currSlide.data.src, 'panorama3.jpg');
    assert.equal(pswp.currSlide.data.width, 3200);
    assert.equal(pswp.currSlide.data.height, 800);
    assert.equal(pswp.currSlide.data.msrc, undefined, 'do not stretch normal thumbnails into panoramas');
    assert.equal(controls['panorama-button'].element.title, 'Show normal images');
    assert.equal(controls['panorama-button'].element.role, 'switch');
    assert.equal(controls['panorama-button'].element['aria-checked'], 'true');
    assert.equal(controls['image-button'].element.href, '/panorama_image_view?id=23');
    assert.equal(controls['download-button'].element.href, 'panorama3.jpg');
    assert.equal(controls['loop-button'].element.href, '/panorama_loop_view?timestamp=102');
    assert.equal(controls['mini_timelapse-button'].element.href, '/mini_generate_view?image_id=3&source=panorama');
    assert.equal(controls['chart-button'].element.href, '/chart_view?timestamp=102');
    assert.equal(controls['vs-button'].element.href, '/virtualsky_view?timestamp=102');
    pswp.goTo(2);
    toggle();
    assert.equal(pswp.getNumItems(), 4);
    assert.equal(pswp.currIndex, 3);
    assert.equal(pswp.currSlide.data.src, 'image4.jpg');
    assert.equal(controls['panorama-button'].element['aria-checked'], 'false');
    assert.equal(controls['image-button'].element.href, '/timelapse_image_view?id=4');
    assert.equal(controls['download-button'].element.href, 'image4.jpg');
    assert.equal(controls['loop-button'].element.href, '/image_loop_view?timestamp=103');
    assert.equal(controls['mini_timelapse-button'].element.href, '/mini_generate_view?image_id=4');
    pswp.goTo(1);
    assert.equal(controls['panorama-button'].element.style.display, 'none');
    toggle();
    assert.equal(pswp.currSlide.data.src, 'image2.jpg');
});

test('switching between one panorama and the final normal image keeps both indexes valid', () => {
    const { pswp, toggle } = gallery([false, false, false, true]);
    pswp.goTo(3);
    for (let repeat = 0; repeat < 3; repeat++) {
        toggle();
        assert.equal(pswp.getNumItems(), 1);
        assert.equal(pswp.currIndex, 0);
        assert.equal(pswp.currSlide.data.src, 'panorama4.jpg');
        toggle();
        assert.equal(pswp.currIndex, 3);
        assert.equal(pswp.currSlide.data.src, 'image4.jpg');
    }
});

test('normal images remain accessible without any panoramas', () => {
    const { pswp, controls, toggle } = gallery([false, false]);
    pswp.goTo(1);
    assert.equal(controls['panorama-button'].element.style.display, 'none');
    toggle();
    assert.equal(pswp.getNumItems(), 2);
    assert.equal(pswp.currSlide.data.src, 'image2.jpg');
});
