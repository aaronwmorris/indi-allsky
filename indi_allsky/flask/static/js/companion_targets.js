'use strict';

class CompanionWindowSettings {
    constructor(key, onApply) {
        this.key = key;
        this.alt = document.getElementById('target-min-alt');
        this.moon = document.getElementById('target-moon-distance');
        this.horizon = document.getElementById('target-horizon');
        this.plot = document.getElementById('target-horizon-plot');
        this.note = document.getElementById('target-settings-message');
        this.value = this.read();
        this.fill();
        document.getElementById('target-limits').addEventListener('toggle', event => {
            if (event.target.open) this.draw();
        });
        this.horizon.addEventListener('input', () => { this.note.hidden = true; this.draw(); });
        this.plot.addEventListener('click', event => this.place(event));
        document.getElementById('target-settings-form').addEventListener('submit', event => {
            event.preventDefault();
            try {
                this.value = this.validate(Number(this.alt.value), Number(this.moon.value), this.parse());
                try { localStorage.setItem(this.key, JSON.stringify(this.value)); } catch (_) {}
                this.fill();
                this.note.textContent = 'Limits applied.';
                onApply();
            } catch (error) { this.note.textContent = error.message; }
            this.note.hidden = false;
        });
    }

    validate(min_altitude, moon_distance, horizon) {
        if (!(Number.isFinite(min_altitude) && min_altitude >= 0 && min_altitude <= 90
            && Number.isFinite(moon_distance) && moon_distance >= 0 && moon_distance <= 180)) {
            throw new Error('Check the altitude and Moon separation limits.');
        }
        if (!Array.isArray(horizon) || horizon.length > 72) throw new Error('Use up to 72 horizon points.');
        const points = new Map();
        for (const pair of horizon) {
            if (!Array.isArray(pair) || pair.length !== 2) throw new Error('Enter one azimuth and height per line.');
            const [az, alt] = pair;
            if (!Number.isFinite(az) || az < 0 || az > 360 || !Number.isFinite(alt) || alt < 0 || alt > 90) {
                throw new Error('Use azimuths from 0 to 360° and heights from 0 to 90°.');
            }
            if (points.has(az % 360)) throw new Error('Give each direction one height. Both 0° and 360° are north.');
            points.set(az % 360, alt);
        }
        return {min_altitude, moon_distance, horizon: [...points].sort((a, b) => a[0] - b[0])};
    }

    read() {
        try {
            const data = JSON.parse(localStorage.getItem(this.key));
            return this.validate(data.min_altitude, data.moon_distance, data.horizon);
        } catch (_) { return {min_altitude: 0, moon_distance: 30, horizon: []}; }
    }

    fill() {
        this.alt.value = this.value.min_altitude;
        this.moon.value = this.value.moon_distance;
        this.horizon.value = this.value.horizon.map(pair => pair.join(' ')).join('\n');
        this.note.hidden = true;
        this.draw();
    }

    parse() {
        return this.horizon.value.trim().split(/\n/).filter(line => line.trim()).map(line => {
            const fields = line.trim().split(/[\s,]+/);
            if (fields.length !== 2 || fields.some(f => !f)) throw new Error('Enter one azimuth and height per line.');
            return fields.map(Number);
        });
    }

    draw() {
        const canvas = this.plot;
        if (!canvas.clientWidth) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height, left = 47, bottom = h - 28, top = 13, right = w - 20;
        const x = az => left + az / 360 * (right - left);
        const y = alt => bottom - alt / 90 * (bottom - top);
        const style = getComputedStyle(canvas);
        ctx.clearRect(0, 0, w, h);
        ctx.font = '19px sans-serif';
        ctx.fillStyle = style.color;
        ctx.strokeStyle = style.getPropertyValue('--line');
        ctx.lineWidth = 1;
        for (const alt of [0, 30, 60, 90]) {
            ctx.textAlign = 'right'; ctx.fillText(alt + '°', left - 5, y(alt) + 5);
            ctx.beginPath(); ctx.moveTo(left, y(alt)); ctx.lineTo(right, y(alt)); ctx.stroke();
        }
        ctx.textAlign = 'center';
        ['N', 'E', 'S', 'W', 'N'].forEach((label, i) => ctx.fillText(label, x(i * 90), h - 3));
        let points;
        try { points = this.validate(0, 0, this.parse()).horizon; } catch (_) { return; }
        let north = 0;
        if (points.length) {
            const [first, firstAlt] = points[0], [last, lastAlt] = points[points.length - 1];
            north = lastAlt + (firstAlt - lastAlt) * (360 - last) / (360 - last + first);
        }
        ctx.strokeStyle = style.color; ctx.fillStyle = style.color; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(left, y(north));
        for (const [az, alt] of points) ctx.lineTo(x(az), y(alt));
        ctx.lineTo(right, y(north)); ctx.stroke();
        for (const [az, alt] of points) {
            ctx.beginPath(); ctx.arc(x(az), y(alt), 4, 0, 2 * Math.PI); ctx.fill();
        }
    }

    place(event) {
        const canvas = this.plot, rect = canvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width * canvas.width;
        const y = (event.clientY - rect.top) / rect.height * canvas.height;
        if (x < 47 || x > canvas.width - 20 || y < 13 || y > canvas.height - 28) return;
        const az = Math.round((x - 47) / (canvas.width - 67) * 72) * 5 % 360;
        const alt = Math.round((canvas.height - 28 - y) / (canvas.height - 41) * 90);
        try {
            const points = new Map(this.validate(0, 0, this.parse()).horizon);
            points.set(az, alt);
            const sorted = this.validate(0, 0, [...points]).horizon;
            this.horizon.value = sorted.map(pair => pair.join(' ')).join('\n');
            this.note.hidden = true;
            this.draw();
        } catch (error) { this.note.textContent = error.message; this.note.hidden = false; }
    }
}

// The slider advances in absolute minutes. Only the time field uses the camera's
// wall clock, so crossing midnight or a clock change never moves the marker.
class CompanionPathEditor {
    constructor(onPreview, onSave) {
        this.box = document.getElementById('target-end-tools');
        this.slider = document.getElementById('target-end-slider');
        this.time = document.getElementById('target-end-time');
        this.set = document.getElementById('target-end-set');
        this.auto = document.getElementById('target-end-auto');
        this.note = document.getElementById('target-end-note');
        this.slider.addEventListener('input', () => this.preview(Number(this.slider.value) * 60000));
        this.time.addEventListener('change', () => {
            // Some wall times occur twice, or never, on a daylight-saving change.
            // Find the next actual projected instant bearing that time.
            for (let m = this.first; m <= this.last; ++m) {
                const at = m * 60000;
                if (at > this.now && this.localTime(at) === this.time.value && this.clip(at)) {
                    this.preview(at);
                    return;
                }
            }
            this.preview(null, 'Choose a future camera time on the visible path.');
        });
        this.set.addEventListener('click', () => {
            if (Number.isFinite(this.draft) && this.draft > this.now) onSave(new Date(this.draft).toISOString());
        });
        this.auto.addEventListener('click', () => { this.draft = null; onSave(null); });
        this.onPreview = onPreview;
    }

    // Build the line and exact interpolated endpoint without joining off-image gaps.
    clip(at) {
        const track = [];
        let previous;
        for (const point of this.samples || []) {
            if (!point) { previous = null; track.push(null); continue; }
            const time = Date.parse(point.at);
            if (time === at) return {track: [...track, point], intersection: point};
            if (time > at && previous) {
                const t0 = Date.parse(previous.at);
                if (t0 > at) return null;
                const f = (at - t0) / (time - t0);
                const intersection = {x: previous.x + f * (point.x - previous.x), y: previous.y + f * (point.y - previous.y)};
                return {track: [...track, intersection], intersection};
            }
            if (time > at) return null;
            track.push(point);
            previous = point;
        }
        return null;
    }

    preview(at, error = '') {
        this.draft = at;
        this.error = error;
        this.onPreview();
    }

    reset() {
        this.draft = null;
        this.error = '';
        this.box.hidden = true;
    }

    show(key, plan, setup, mark, now, localTime) {
        if (key !== this.key || this.setup !== setup) this.reset();
        this.key = key;
        this.setup = setup;
        this.now = now;
        this.localTime = localTime;
        this.samples = plan?.edit_path;
        const samples = this.samples?.filter(Boolean);
        this.box.hidden = !(setup && localTime && (samples?.length > 1 || mark));
        if (this.box.hidden) return null;
        this.slider.disabled = this.time.disabled = !(samples?.length > 1);
        if (this.slider.disabled) {
            this.set.disabled = true;
            this.auto.disabled = false;
            this.time.value = localTime(Date.parse(mark));
            this.note.textContent = 'No editable path in this image.';
            return null;
        }
        this.first = Math.ceil(Math.max(now + 1, Date.parse(samples[0].at)) / 60000);
        this.last = Math.floor(Date.parse(samples.at(-1).at) / 60000);
        if (this.first > this.last) { this.box.hidden = true; return null; }
        this.slider.min = this.first;
        this.slider.max = this.last;
        if (this.draft && this.draft <= now) this.reset();
        this.box.hidden = false;
        const hasCrossing = ['obstacle', 'horizon', 'geometric_horizon', 'user_marked'].includes(plan.track_end_reason);
        const current = hasCrossing ? Date.parse(plan.track_ends_at) : NaN;
        const minute = Math.min(this.last, Math.max(this.first, Math.floor((this.draft ?? (current || this.first * 60000)) / 60000)));
        this.slider.value = minute;
        const at = minute * 60000;
        if (!this.error) this.time.value = this.draft || Number.isFinite(current) ? localTime(at) : '';
        const clipped = this.draft && this.clip(this.draft);
        this.set.disabled = !clipped;
        this.auto.disabled = !this.draft && !this.error && !mark;
        const status = {outside_pass: 'Marked time is outside this pass.', outside_image: 'Marked position is outside the image.',
            unavailable: 'Marked position unavailable.', out_of_range: 'Marked time is outside this forecast.',
            setup_changed: 'Camera setup changed.', expired: 'Marked time has passed.'};
        const when = localTime(at, false, now);
        this.note.textContent = this.error || (this.draft && !clipped ? 'Outside the camera image.' : '') ||
            (clipped ? when + ' camera time' : status[plan.manual_end_status] ||
                (Number.isFinite(current) ? 'Camera local time' : 'Move the slider or enter a camera time.'));
        if (!this.draft) return null;
        return clipped ? {...clipped, track_end_reason: 'user_marked', track_ends_at: new Date(this.draft).toISOString()} :
            {track: [], intersection: null, track_end_reason: null};
    }
}

class CompanionTargets {
    constructor(page) {
        this.endpoint = page.dataset.endpoint;
        this.key = 'allsky-companion-targets-' + page.dataset.cameraId;
        this.dialog = document.getElementById('target-dialog');
        this.overlay = document.getElementById('target-markers');
        this.geometry = document.getElementById('target-geometry');
        this.pathChoice = document.getElementById('target-path-choice');
        this.pathTools = document.getElementById('target-path-tools');
        this.pathEditor = new CompanionPathEditor(() => this.drawPath(), at => this.setEndTime(at));
        this.pathChoice.addEventListener('change', () => { this.drawPath(); this.refresh(); });
        this.list = document.getElementById('target-list');
        this.open = document.getElementById('target-open');
        this.form = document.getElementById('target-form');
        this.mode = document.getElementById('target-mode');
        this.name = document.getElementById('target-name');
        this.ra = document.getElementById('target-ra');
        this.dec = document.getElementById('target-dec');
        this.label = document.getElementById('target-label');
        this.addButton = document.getElementById('target-add');
        this.onlineButton = document.getElementById('target-online');
        this.conditions = document.getElementById('target-conditions');
        this.settings = new CompanionWindowSettings(this.key + '-limits', () => {
            this.windows = [];
            this.refresh();
        });
        this.targets = this.readTargets();
        this.open.addEventListener('click', () => {
            this.dialog.showModal();
            this.settings.fill();
            (this.mode.value === 'coords' ? this.ra : this.name).focus();
        });
        document.getElementById('target-close').addEventListener('click', () => this.dialog.close());
        this.form.addEventListener('submit', event => {
            event.preventDefault();
            return this.add();
        });
        this.onlineButton.addEventListener('click', () => this.add(true));
        this.form.addEventListener('input', () => this.resetLookup());
        this.dialog.addEventListener('close', () => this.resetLookup());
        this.mode.addEventListener('change', () => {
            const coords = this.mode.value === 'coords';
            document.getElementById('target-name-fields').hidden = coords;
            document.getElementById('target-coord-fields').hidden = !coords;
            this.name.disabled = coords;
            for (const input of [this.ra, this.dec, this.label]) input.disabled = !coords;
            this.resetLookup();
        });
        window.addEventListener('storage', event => {
            if (event.key === this.settings.key || event.key === null) {
                this.settings.value = this.settings.read();
                if (!this.dialog.open) this.settings.fill();
                this.windows = [];
                if (event.key !== null) this.refresh();
            }
            if (event.key === this.key || event.key === null) {
                this.targets = this.readTargets();
                this.renderList();
                this.refresh();
            }
        });
        document.addEventListener('visibilitychange', () => this.refresh());
        window.addEventListener('pagehide', () => { this.pageHidden = true; this.stopProjection(); });
        window.addEventListener('pageshow', event => {
            if (event.persisted) { this.pageHidden = false; this.refresh(); }
        });
        if (typeof ResizeObserver === 'function') {
            this.resizeObserver = new ResizeObserver(() => this.resize());
            this.resizeObserver.observe(this.overlay.parentElement);
        } else {
            window.addEventListener('resize', () => this.resize());
        }
        this.renderList();
    }

    readTargets() {
        try {
            const saved = JSON.parse(localStorage.getItem(this.key));
            if (Array.isArray(saved)) return saved.filter(t => t && typeof t.label === 'string'
                && t.label && Number.isFinite(t.ra_deg) && t.ra_deg >= 0 && t.ra_deg < 360
                && Number.isFinite(t.dec_deg) && Math.abs(t.dec_deg) <= 90);
        } catch (_) { /* Target entry still works when browser storage is unavailable. */ }
        return [];
    }

    writeTargets() {
        try { localStorage.setItem(this.key, JSON.stringify(this.targets)); } catch (_) {}
    }

    save() {
        this.writeTargets();
        this.renderList();
        this.refresh();
    }

    selectedIndex() {
        return this.targets.findIndex(t => t.ra_deg + ',' + t.dec_deg === this.pathChoice.value);
    }

    savedEnd(target) {
        const mark = target?.path_end;
        const at = Date.parse(mark?.at);
        return this.frameId && this.setupId && mark?.setup === this.setupId && Number.isFinite(at) &&
            Math.abs(at - this.now) <= 86400000 ? mark.at : '';
    }

    setEndTime(at) {
        const target = this.targets[this.selectedIndex()];
        if (!target || !this.setupId || this.geometryFrameId !== this.frameId) return;
        if (at) target.path_end = {setup: this.setupId, at};
        else delete target.path_end;
        this.writeTargets();
        this.pathEditor.reset();
        this.refresh();
    }

    message(id, text) {
        const element = document.getElementById(id);
        element.textContent = text;
        element.hidden = !text;
    }

    async request(params, signal) {
        const url = new URL(this.endpoint, document.baseURI);
        for (const [key, value] of params) url.searchParams.append(key, value);
        const response = await fetch(url, {
            credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}, signal,
        });
        if (!response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('Could not reach the camera. Check your connection and sign-in.');
        }
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(data.error || 'Could not update target markers.');
            error.code = data.code;
            throw error;
        }
        return data;
    }

    resetLookup() {
        this.lookup?.abort();
        this.lookup = null;
        this.unknownName = null;
        this.onlineButton.hidden = true;
        this.onlineButton.disabled = false;
        this.addButton.disabled = false;
        this.message('target-error', '');
    }

    async add(online = false) {
        if (this.lookup) return;
        const coords = this.mode.value === 'coords';
        const name = this.name.value.trim();
        if (online && (coords || !name || this.unknownName !== name)) return;
        const params = coords ? [['ra', this.ra.value.trim()], ['dec', this.dec.value.trim()]]
            : [['resolve', name]];
        if (online) params.push(['online', '1']);
        const label = coords ? this.label.value.trim() : '';
        this.onlineButton.hidden = !online;
        this.onlineButton.disabled = true;
        this.addButton.disabled = true;
        this.message('target-error', online ? 'Searching CDS…' : '');
        const request = new AbortController();
        this.lookup = request;
        const timeout = setTimeout(() => request.abort(), 12000);
        try {
            const {target} = await this.request(params, request.signal);
            if (this.lookup !== request) return;
            if (request.signal.aborted) throw new Error('Target lookup timed out. Try again.');
            if (!target || !Number.isFinite(target.ra_deg) || !Number.isFinite(target.dec_deg) || !target.label) {
                throw new Error('The camera returned an invalid target.');
            }
            this.onlineButton.hidden = true;
            this.unknownName = null;
            if (this.targets.some(t => t.ra_deg === target.ra_deg && t.dec_deg === target.dec_deg)) {
                throw new Error('This target is already on the list.');
            }
            this.targets = [...this.targets, {label: label || target.label, ra_deg: target.ra_deg, dec_deg: target.dec_deg}];
            this.save();
            for (const field of [this.name, this.ra, this.dec, this.label]) field.value = '';
            this.message('target-error', '');
            (coords ? this.ra : this.name).focus();
        } catch (error) {
            if (this.lookup !== request) return;
            if (!online) this.unknownName = !coords && error.code === 'unknown_name' ? name : null;
            if (online && error.code === 'online_unknown') this.unknownName = null;
            this.onlineButton.hidden = !this.unknownName;
            this.message('target-error', request.signal.aborted ? 'Target lookup timed out. Try again.' : error.message);
        } finally {
            clearTimeout(timeout);
            if (this.lookup === request) {
                this.lookup = null;
                this.onlineButton.disabled = false;
                this.addButton.disabled = false;
            }
        }
    }

    renderList() {
        this.open.textContent = this.targets.length ? 'Targets (' + this.targets.length + ')' : 'Targets';
        this.visibilityNotes = [];
        const rows = this.targets.map(target => {
            const row = document.createElement('li');
            const label = document.createElement('span');
            label.textContent = target.label;
            label.title = 'RA ' + target.ra_deg.toFixed(4) + '° · Dec ' + target.dec_deg.toFixed(4) + '° (J2000)';
            const note = document.createElement('small');
            note.textContent = 'Outside view';
            note.hidden = true;
            this.visibilityNotes.push(note);
            label.append(note);
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = 'Remove';
            remove.setAttribute('aria-label', 'Remove ' + target.label);
            remove.addEventListener('click', () => {
                this.targets = this.targets.filter(item => item !== target);
                this.save();
            });
            row.append(label, remove);
            return row;
        });
        this.list.replaceChildren(...rows);
        this.overlay.replaceChildren();
        const previous = this.pathChoice.value;
        const choices = this.targets.map(t => new Option(t.label, t.ra_deg + ',' + t.dec_deg));
        this.pathChoice.replaceChildren(new Option('Off', ''), ...choices);
        this.pathChoice.value = choices.some(o => o.value === previous) ? previous : '';
        this.geometry.hidden = this.pathTools.hidden = true;
        this.conditions.hidden = !this.targets.length;
        this.windowRows = [];
        this.windows = [];
        this.qualities = [];
        const cards = this.targets.map(target => {
            const item = document.createElement('li');
            const details = document.createElement('details');
            details.className = 'target-row';
            const summary = document.createElement('summary');
            const name = document.createElement('strong');
            name.textContent = target.label;
            const orbit = document.createElement('small');
            orbit.className = 'target-orbit';
            orbit.textContent = ' · Circumpolar';
            orbit.title = 'Stays above the geometric horizon at this location.';
            orbit.hidden = true;
            name.append(orbit);
            const sky = document.createElement('span');
            sky.className = 'target-sky';
            const time = document.createElement('span');
            time.className = 'target-window';
            const description = document.createElement('p');
            description.className = 'target-detail';
            summary.append(name, sky, time);
            details.append(summary, description);
            item.append(details);
            this.windowRows.push({sky, time, description, orbit});
            return item;
        });
        document.getElementById('target-conditions-list').replaceChildren(...cards);
        this.renderConditions();
    }

    showFrame(entry, image) {
        this.image = image;
        this.frameId = entry.time_source === 'capture' && Number.isSafeInteger(entry.id) ? entry.id : null;
        this.captureTime = this.frameId ? entry.captured_at : null;
        this.qualities = [];
        this.overlay.replaceChildren();
        this.geometry.hidden = this.pathTools.hidden = true;
        this.pathEditor.box.hidden = true;
        this.renderConditions();
        this.resize();
        this.refresh();
    }

    resize() {
        if (!this.image?.naturalWidth || !this.targets.length) return;
        // The img element fills its box; object-fit:contain may leave black bars.
        const scale = Math.min(this.image.clientWidth / this.image.naturalWidth, this.image.clientHeight / this.image.naturalHeight);
        this.overlay.style.width = this.image.naturalWidth * scale + 'px';
        this.overlay.style.height = this.image.naturalHeight * scale + 'px';
        this.geometry.style.width = this.overlay.style.width;
        this.geometry.style.height = this.overlay.style.height;
    }

    drawPath() {
        if (!this.frameId || this.geometryFrameId !== this.frameId) {
            this.geometry.hidden = this.pathTools.hidden = this.pathEditor.box.hidden = true;
            return;
        }
        const selected = this.selectedIndex();
        const plan = this.windows[selected];
        const draft = this.pathEditor.show(this.pathChoice.value, plan, this.setupId,
            this.savedEnd(this.targets[selected]), this.now, this.localTime);
        const window = draft ? {...plan, ...draft} : plan;
        const inside = p => p && Number.isFinite(p.x) && p.x >= 0 && p.x <= 1 &&
            Number.isFinite(p.y) && p.y >= 0 && p.y <= 1;
        // Each null separates visible segments; joining across it could draw
        // through an obstruction or outside the calibrated field of view.
        const pathData = (points, keepDots = false) => {
            const segments = [];
            let run = [];
            const finish = () => {
                if (run.length > 1) segments.push('M' + run.join('L'));
                // A measured twig tip between gaps still has a position. A
                // short stroke with a round cap makes exactly that point visible.
                else if (run.length && keepDots) segments.push('M' + run[0] + 'l.01 0');
                run = [];
            };
            for (const p of points || []) {
                if (!inside(p)) { finish(); continue; }
                run.push((1000 * p.x).toFixed(2) + ' ' + (1000 * p.y).toFixed(2));
            }
            finish();
            return segments.join('');
        };
        const track = pathData(window?.track);
        const skyline = track ? pathData(this.skyline, true) : '';
        document.getElementById('observed-skyline').setAttribute('d', skyline);
        document.getElementById('projected-track').setAttribute('d', track);
        const cross = document.getElementById('target-crossing');
        const endReason = window?.track_end_reason;
        const crossings = {obstacle: 'Estimated edge', horizon: 'User horizon', geometric_horizon: 'Geometric horizon',
            user_marked: draft ? 'Preview' : 'Marked end'};
        const showCross = !!track && !!crossings[endReason] && inside(window?.intersection);
        cross.hidden = !showCross;
        if (showCross) {
            cross.style.left = window.intersection.x * 100 + '%';
            cross.style.top = window.intersection.y * 100 + '%';
        }
        this.geometry.hidden = !track;
        this.pathTools.hidden = !this.setupId && !this.windows.some(plan => plan?.track?.length > 1);
        const estimated = window?.horizon_basis === 'estimated';
        const skylineKey = document.getElementById('skyline-key');
        skylineKey.textContent = estimated ? 'Estimated skyline' : 'Observed skyline';
        skylineKey.hidden = !skyline;
        let note = crossings[endReason] || '';
        if (note) {
            const end = Date.parse(window.track_ends_at);
            if (Number.isFinite(end) && this.localTime) note += ' at ' + this.localTime(end, false, this.now);
            if (showCross) note = '× ' + note;
        } else if (endReason === 'unmapped') {
            note = 'Path reaches unverified sky';
        } else if (endReason === 'forecast_limit') {
            note = estimated ? 'No skyline crossing predicted in the next 24 h' : 'No horizon crossing in the next 24 h';
            if (window.horizon_basis === 'geometric') note = 'No geometric horizon crossing in the next 24 h · terrain unverified';
            if (window.horizon_basis === 'partial') note += ' · partial skyline coverage';
        }
        if (window?.circumpolar) {
            const reappears = Date.parse(window.track_reappears_at);
            if (['obstacle', 'horizon'].includes(endReason) && Number.isFinite(reappears) && this.localTime) {
                note += (estimated ? ' · expected to reappear at ' : ' · clears the obstruction at ') +
                    this.localTime(reappears, false, this.now);
            }
            if (!note && window.horizon_basis === 'partial') note = 'Visibility unverified in this direction';
            note = 'Circumpolar' + (note ? ' · ' + note : '');
        }
        const start = Date.parse(window?.track_starts_at);
        if (track && this.localTime && start > this.windowAt + 60000) {
            note = 'From ' + this.localTime(start, false, this.now) + (note ? ' · ' + note : '');
        }
        const key = document.getElementById('crossing-key');
        key.textContent = note;
        key.hidden = !note || (!track && !(window?.circumpolar && this.setupId));
    }

    tick(now, localTime) {
        this.now = now;
        this.localTime = localTime;
        if (!this.targets.length || document.hidden || this.pageHidden) return;
        // Also request a forecast before the first image or when capture is paused.
        if (!this.projection && !this.retry && (this.lastRequest == null || performance.now() - this.lastRequest >= 60000)) {
            this.refresh();
        }
        const minute = Math.floor(now / 60000);
        if (this.minute !== minute) {
            this.minute = minute;
            this.renderConditions();
            this.drawPath();
        }
    }

    renderConditions() {
        if (!this.targets.length) return;
        const frameTime = this.captureTime?.match(/T(\d\d:\d\d)/)?.[1];
        const header = document.getElementById('target-frame-time');
        header.textContent = frameTime ? 'Sky at ' + frameTime : 'Sky unmeasured';
        header.title = this.captureTime || 'No saved frame';
        const labels = {clear: 'Clear', thin_cloud: 'Possible thin cloud', obscured: 'Obscured', unknown: 'Unassessed'};
        const limits = {altitude: 'minimum altitude', horizon: 'local horizon', twilight: 'twilight',
            moon: 'Moon separation', obstacle: 'observed obstruction', unmapped: 'unverified skyline', user_marked: 'marked end',
            missing_location: 'camera location unavailable'};
        for (const [i, row] of this.windowRows.entries()) {
            const q = this.qualities[i], plan = this.windows[i];
            const state = typeof labels[q?.state] === 'string' ? q.state : 'unknown';
            row.sky.dataset.state = state;
            row.sky.textContent = labels[state];
            row.orbit.hidden = !plan?.circumpolar;
            const estimated = plan?.horizon_basis === 'estimated';
            const limit = reason => estimated && reason === 'obstacle' ? 'estimated obstruction' : limits[reason];
            const start = Date.parse(plan?.starts_at), end = Date.parse(plan?.ends_at);
            const ref = this.now ?? this.windowAt;
            const time = ts => this.localTime ? this.localTime(ts, false, ref) : new Date(ts).toISOString().slice(11, 16) + ' UTC';
            const duration = ms => {
                const mins = Math.max(0, Math.floor(ms / 60000));
                if (!mins) return '<1 min';
                const h = Math.floor(mins / 60);
                return h ? h + ' h' + (mins % 60 ? ' ' + mins % 60 + ' min' : '') : mins + ' min';
            };
            let windowText = 'Window unavailable';
            if (plan?.state === 'open' && Number.isFinite(end) && end > ref) {
                if (plan.end_reason === 'unmapped') {
                    windowText = 'Verified for ' + duration(end - ref) + ' · beyond ' + time(end) + ' unverified';
                } else {
                    windowText = duration(end - ref) + ' left · until ' + time(end);
                    if (limit(plan.end_reason)) windowText += ' (' + limit(plan.end_reason) + ')';
                }
            } else if (plan?.state === 'open' && plan.end_reason === 'forecast_limit') {
                windowText = 'Open through the 24 h forecast';
            } else if (plan?.state === 'upcoming' && Number.isFinite(start) && start > ref) {
                windowText = 'Opens in ' + duration(start - ref) + ' · ' + time(start);
                if (Number.isFinite(end)) windowText += '–' + time(end);
                if (plan.end_reason === 'unmapped') windowText += ' (unverified beyond)';
                else if (plan.end_reason === 'obstacle') windowText += ' (' + limit('obstacle') + ')';
                else if (plan.end_reason === 'user_marked') windowText += ' (marked end)';
            } else if (plan?.state === 'none' && plan.reason === 'user_marked') {
                windowText = 'Pass ended' + (Number.isFinite(end) ? ' at ' + time(end) : '') + ' (marked end)';
            } else if (plan?.state === 'none' && plan.manual_end_status === 'applied') {
                const markedEnd = Date.parse(plan.track_ends_at);
                windowText = 'No imaging window before marked end' + (Number.isFinite(markedEnd) ? ' at ' + time(markedEnd) : '');
            } else if (plan?.state === 'none') {
                windowText = 'No window in the next 24 h';
            } else if (plan?.state === 'unknown' && plan.reason === 'unmapped') {
                windowText = 'Visibility unverified in this direction';
            } else if (plan?.state === 'open' || plan?.state === 'upcoming') {
                windowText = 'Updating window…';
            }
            const marked = plan?.manual_end_status === 'applied' || plan?.reason === 'user_marked';
            row.time.textContent = !marked && plan?.horizon_basis === 'geometric' ? windowText + ' · terrain unverified' : windowText;
            const detail = [];
            if (q?.reason) detail.push(q.reason);
            if (marked) detail.push('This pass uses your marked end.');
            else if (estimated) detail.push('Window follows the estimated skyline.');
            else if (plan?.horizon_basis === 'partial') detail.push('Skyline measured in part of the image.');
            else if (plan?.horizon_basis === 'image') detail.push('Window follows the observed skyline.');
            const reopens = Date.parse(plan?.reopens_at);
            const clears = Date.parse(plan?.track_reappears_at);
            if (plan?.circumpolar && ['obstacle', 'horizon'].includes(plan.track_end_reason) && Number.isFinite(clears)) {
                detail.push((estimated ? 'Expected to reappear at ' : 'Clears the obstruction at ') + time(clears) + '.');
            }
            if (plan?.end_reason === 'obstacle' && Number.isFinite(reopens)) {
                detail.push((estimated ? 'Next imaging window expected at ' : 'Next imaging window at ') + time(reopens) + '.');
            }
            if (Number.isFinite(plan?.altitude_deg) && Number.isFinite(plan.azimuth_deg)) {
                detail.push('Altitude ' + Math.round(plan.altitude_deg) + '° · Azimuth ' + Math.round(plan.azimuth_deg) + '°.');
            }
            if (Number.isFinite(plan?.moon_distance_deg) && plan.moon_up) {
                detail.push('Moon separation ' + Math.round(plan.moon_distance_deg) + '°.');
            }
            if (limit(plan?.reason)) detail.push('Current limit: ' + limit(plan.reason) + '.');
            if (Number.isFinite(this.windowAt) && plan) detail.push('Window calculated at ' + time(this.windowAt) + '.');
            row.description.textContent = detail.join(' ') || 'Waiting for camera data.';
        }
    }

    stopProjection() {
        this.projection?.abort();
        this.projection = null;
        clearTimeout(this.retry);
        this.retry = null;
    }

    async refresh() {
        this.stopProjection();
        if (!this.targets.length || !this.frameId) this.overlay.replaceChildren();
        this.message('target-status', this.targets.length && !this.frameId ? 'Markers need a saved, aligned image.' : '');
        if (!this.targets.length || document.hidden || this.pageHidden) return;
        this.resize();
        const request = new AbortController();
        this.projection = request;
        this.lastRequest = performance.now();
        const points = [], qualities = [], windows = [], projected = [];
        let skyline = [], setup = null;
        const selected = this.selectedIndex();
        try {
            // Batch large lists to fit browser and server URL limits.
            for (let i = 0; i < this.targets.length; i += 32) {
                const batch = this.targets.slice(i, i + 32);
                const params = [['target_settings', JSON.stringify(this.settings.value)],
                    ...batch.map(t => ['target', t.ra_deg + ',' + t.dec_deg])];
                if (this.frameId) params.push(['frame', this.frameId]);
                if (this.frameId && selected >= i && selected < i + batch.length) params.push(['edit_path', selected - i]);
                const ends = batch.map(t => this.savedEnd(t));
                if (ends.some(Boolean)) params.push(['path_end_setup', this.setupId], ...ends.map(t => ['path_end_at', t]));
                const timeout = setTimeout(() => request.abort(), 12000);
                let response;
                try { response = await this.request(params, request.signal); } finally { clearTimeout(timeout); }
                if (this.projection !== request || request.signal.aborted || response.frame !== (this.frameId ?? null)) return;
                if (response.state !== 'ready') {
                    if (this.frameId) this.message('target-status', response.state === 'orientation_pending'
                        ? 'Waiting for star alignment on this image.' : 'Target positions are unavailable for this image.');
                }
                if (!Array.isArray(response.points) || response.points.length !== batch.length) throw new Error('Invalid positions');
                points.push(...response.points);
                if (response.state === 'ready' && response.setup_id) setup = response.setup_id;
                if (response.state === 'ready' && Array.isArray(response.skyline)) skyline = response.skyline;
                for (let j = 0; j < batch.length; j++) {
                    qualities.push(response.qualities?.[j] || null);
                    windows.push(response.windows?.[j] || null);
                    projected.push(response.state === 'ready');
                }
                if (response.window_at) this.windowAt = Date.parse(response.window_at);
            }
            this.qualities = qualities;
            this.windows = windows;
            this.skyline = skyline;
            this.geometryFrameId = this.frameId;
            const setupChanged = setup !== this.setupId;
            this.setupId = setup;
            this.renderConditions();
            this.drawPath();
            const markers = [];
            for (const [i, point] of points.entries()) {
                this.visibilityNotes[i].hidden = true;
                if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)
                    || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) {
                    this.visibilityNotes[i].hidden = !projected[i];
                    continue;
                }
                const mark = document.createElement('span');
                mark.className = 'target-marker';
                mark.dataset.state = qualities[i]?.state || 'unknown';
                mark.style.left = (100 * point.x) + '%';
                mark.style.top = (100 * point.y) + '%';
                const name = document.createElement('span');
                name.textContent = this.targets[i].label;
                if (point.x > .5) name.className = 'label-before';
                mark.append(name);
                markers.push(mark);
            }
            this.overlay.replaceChildren(...markers);
            // A reopened Companion learns the current setup from its first
            // frame. Only then may it submit a setting saved for that setup.
            if (setupChanged && setup && this.targets.some(t => this.savedEnd(t))) this.refresh();
        } catch (_) {
            if (this.projection !== request) return;
            this.message('target-status', 'Could not load target conditions. Retrying…');
            this.windows = [];
            this.setupId = null;
            this.geometryFrameId = null;
            this.renderConditions();
            this.drawPath();
            this.retry = setTimeout(() => this.refresh(), 10000);
        } finally {
            if (this.projection === request) this.projection = null;
        }
    }
}
