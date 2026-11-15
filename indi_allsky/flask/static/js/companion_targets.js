'use strict';

class CompanionTargets {
    constructor(page) {
        this.endpoint = page.dataset.endpoint;
        this.key = 'allsky-companion-targets-' + page.dataset.cameraId;
        this.dialog = document.getElementById('target-dialog');
        this.overlay = document.getElementById('target-markers');
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
        this.targets = this.readTargets();
        this.open.addEventListener('click', () => {
            this.dialog.showModal();
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
            if (event.key === this.key || event.key === null) {
                this.targets = this.readTargets();
                this.renderList();
                this.refresh();
            }
        });
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.targets.length) this.refresh();
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

    save() {
        try { localStorage.setItem(this.key, JSON.stringify(this.targets)); } catch (_) {}
        this.renderList();
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
    }

    showFrame(entry, image) {
        this.image = image;
        this.frameId = entry.time_source === 'capture' && Number.isSafeInteger(entry.id) ? entry.id : null;
        this.resize();
        this.refresh();
    }

    resize() {
        if (!this.image?.naturalWidth || !this.targets.length) return;
        // The img element fills its box; object-fit:contain may leave black bars.
        const scale = Math.min(this.image.clientWidth / this.image.naturalWidth, this.image.clientHeight / this.image.naturalHeight);
        this.overlay.style.width = this.image.naturalWidth * scale + 'px';
        this.overlay.style.height = this.image.naturalHeight * scale + 'px';
    }

    async refresh() {
        this.projection?.abort();
        this.projection = null;
        clearTimeout(this.retry);
        this.overlay.replaceChildren();
        for (const note of this.visibilityNotes) note.hidden = true;
        this.message('target-status', this.targets.length && !this.frameId ? 'Markers need a saved, aligned image.' : '');
        if (!this.targets.length || !this.frameId || document.hidden) return;
        this.resize();
        const request = new AbortController();
        this.projection = request;
        const points = [];
        try {
            // Batch large lists to fit browser and server URL limits.
            for (let i = 0; i < this.targets.length; i += 32) {
                const batch = this.targets.slice(i, i + 32);
                const params = [['frame', this.frameId], ...batch.map(t => ['target', t.ra_deg + ',' + t.dec_deg])];
                const timeout = setTimeout(() => request.abort(), 12000);
                let response;
                try { response = await this.request(params, request.signal); } finally { clearTimeout(timeout); }
                if (this.projection !== request || request.signal.aborted || response.frame !== this.frameId) return;
                if (response.state !== 'ready') {
                    this.message('target-status', response.state === 'orientation_pending'
                        ? 'Waiting for star alignment on this image.' : 'Target positions are unavailable for this image.');
                    return;
                }
                if (!Array.isArray(response.points) || response.points.length !== batch.length) throw new Error('Invalid positions');
                points.push(...response.points);
            }
            const markers = [];
            for (const [i, point] of points.entries()) {
                if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)
                    || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) {
                    this.visibilityNotes[i].hidden = false;
                    continue;
                }
                const mark = document.createElement('span');
                mark.className = 'target-marker';
                mark.style.left = (100 * point.x) + '%';
                mark.style.top = (100 * point.y) + '%';
                const name = document.createElement('span');
                name.textContent = this.targets[i].label;
                if (point.x > .5) name.className = 'label-before';
                mark.append(name);
                markers.push(mark);
            }
            this.overlay.replaceChildren(...markers);
        } catch (_) {
            if (this.projection !== request) return;
            this.message('target-status', 'Could not load target positions. Retrying…');
            this.retry = setTimeout(() => this.refresh(), 10000);
        }
    }
}
