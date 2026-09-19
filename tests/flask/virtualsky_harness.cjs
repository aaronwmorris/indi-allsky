const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Run the real browser library without a canvas or network. An empty id is
// VirtualSky's supported non-rendering mode; coordinate methods remain active.
function makeSky(options = {}, asset = 'virtualsky.js') {
    const query = {
        attr: () => ['/static/virtualsky/virtualsky.js'],
        append() { return this; },
        ajax() { return this; },
    };
    const S = () => query;
    const context = vm.createContext({
        S, stuQuery: function () {}, document: {}, window: {setTimeout, clearTimeout},
        location: {search: '', host: 'localhost', href: ''},
        navigator: {language: 'en'}, Date, console,
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname,
        '../../indi_allsky/flask/static/virtualsky', asset), 'utf8'), context);
    return S.virtualsky({projection: 'fisheye', width: 1000, height: 1000,
        latitude: 46.51, longitude: 8, clock: new Date(1770000000000),
        az: 180, ...options});
}

module.exports = {makeSky};
