'use strict';

(() => {
    const page = document.getElementById('companion');
    const byId = id => document.getElementById(id);
    const selects = [byId('series-1'), byId('series-2')];
    const charts = [null, null];
    const storageKey = 'allsky-companion-charts-' + page.dataset.cameraId;
    const interval = Math.max(5000, Number(page.dataset.refreshMs) || 15000);
    const eventNames = ['evening_start', 'evening_end', 'morning_start', 'morning_end', 'moon_rise', 'moon_set'];
    const eventDate = new Intl.DateTimeFormat('en', {month: 'short', day: 'numeric', timeZone: 'UTC'});
    const number = new Intl.NumberFormat('en', { maximumFractionDigits: 2 });
    const lowNumber = new Intl.NumberFormat('en', { maximumSignificantDigits: 3 });
    const formatReading = value => value !== 0 && Math.abs(value) < .1 ? lowNumber.format(value) : number.format(value);
    let choices = null;
    let clock = null;
    let formats;
    let displayed = null;
    let imageMessage = '';
    let imageServiceMessage = '';
    let detailMessage = '';
    let capturePaused = false;
    let lastPayload;
    const staleAfter = Number(page.dataset.staleMs) || 90000;

    try {
        const saved = JSON.parse(localStorage.getItem(storageKey));
        if (Array.isArray(saved) && saved.length === 2 && saved.every(id => typeof id === 'string')) {
            choices = saved;
        }
    } catch (_) { /* The page works without saved settings. */ }

    function cameraNow() {
        return clock.timestamp + performance.now() - clock.syncedAt;
    }

    function localTime(timestamp, withSeconds = false) {
        const value = formats.useOffset ? timestamp + clock.offset * 60000 : timestamp;
        return (withSeconds ? formats.seconds : formats.minutes).format(value);
    }

    function clockFormats(zone) {
        const make = timeZone => {
            const options = {timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'};
            return {
                zone, useOffset: !zone || zone !== timeZone,
                minutes: new Intl.DateTimeFormat('en', options),
                seconds: new Intl.DateTimeFormat('en', {...options, second: '2-digit'}),
            };
        };
        // Some browsers have an older timezone database than the camera.
        try { return make(zone || 'UTC'); } catch (_) { return make('UTC'); }
    }

    // Each event carries its own camera offset, including across a DST change.
    function dateAndTime(iso) {
        const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(iso || '');
        if (!match) return null;
        return { date: match[1] + '-' + match[2] + '-' + match[3], time: match[4] + ':' + match[5],
            seconds: match[6] || '00' };
    }

    function showEvent(id, iso) {
        const cell = byId(id);
        const formatted = dateAndTime(iso);
        if (!formatted) {
            cell.textContent = '–';
            cell.title = 'No event in this period';
            return;
        }
        cell.removeAttribute('title');
        const time = document.createElement('time');
        time.className = 'event-time';
        time.dateTime = iso;
        time.title = formatted.date + ' · ' + formatted.time;
        const date = document.createElement('span');
        date.className = 'event-date';
        date.textContent = eventDate.format(Date.parse(formatted.date)); // The ISO date is already in camera local time.
        const hour = document.createElement('strong');
        hour.textContent = formatted.time;
        time.append(hour, date);
        cell.replaceChildren(time);
    }

    function imageIsLate() {
        return displayed && clock && cameraNow() - displayed.timestamp > staleAfter;
    }

    function updateStatus() {
        const lines = [];
        if (imageServiceMessage) lines.push(imageServiceMessage);
        else if (frames.active && performance.now() - frames.active.startedAt > 800) {
            lines.push('New capture available · loading image');
        } else if (imageMessage) lines.push(imageMessage);
        else if (capturePaused) lines.push('Pi online · capture paused');
        else if (imageIsLate()) lines.push('Pi online · no new image');
        if (detailMessage && !lines.includes(detailMessage)) lines.push(detailMessage);
        const message = byId('connection-message');
        const text = lines.join(' ');
        if (message.textContent !== text) message.textContent = text;
        message.hidden = !text;
    }

    function tick() {
        if (!clock) return;
        const now = cameraNow();
        byId('clock').textContent = localTime(now, true);
        byId('clock').dateTime = new Date(now).toISOString();
        if (displayed) {
            const seconds = Math.floor(Math.max(0, now - displayed.timestamp) / 1000);
            const days = Math.floor(seconds / 86400);
            const age = seconds < 60 ? seconds + ' s' : seconds < 3600 ? Math.floor(seconds / 60) + ' min'
                : seconds < 86400 ? Math.floor(seconds / 3600) + ' h' : days + (days === 1 ? ' day' : ' days');
            const badge = byId('image-age');
            badge.textContent = age + ' ago';
            badge.classList.toggle('new-frame', performance.now() < displayed.highlightUntil);
            badge.title = imageIsLate() ? 'Time since the last known capture' : 'Latest capture';
        }
        updateStatus();
    }

    const frames = new LiveFrameLoader((image, entry) => {
        imageMessage = '';
        image.id = 'capture-image';
        image.alt = 'Latest all-sky image';
        byId('capture-image').replaceWith(image);
        page.style.setProperty('--capture-aspect', image.naturalWidth / image.naturalHeight);
        byId('empty-image').hidden = true;
        const timestamp = Date.parse(entry.captured_at);
        const advanced = displayed && timestamp > displayed.timestamp && cameraNow() - timestamp < 60000;
        displayed = {timestamp, highlightUntil: advanced ? performance.now() + 3000 : 0};
        const time = byId('image-time');
        const formatted = dateAndTime(entry.captured_at);
        const date = document.createElement('span');
        date.textContent = formatted.date;
        const hour = document.createElement('strong');
        hour.textContent = formatted.time + ':' + formatted.seconds;
        time.replaceChildren(hour, date);
        time.dateTime = entry.captured_at;
        document.querySelector('.caption-label').textContent = entry.time_source === 'file' ? 'File time' : 'Captured';
        tick();
    }, issue => {
        imageMessage = issue === 'timeout' ? 'Image request timed out · retrying' : 'Could not load image · retrying';
        if (!displayed) byId('empty-image').textContent = 'Image unavailable';
        updateStatus();
    });

    function updateImage(entry) {
        if (entry === null) {
            frames.stop();
            imageMessage = capturePaused ? 'Pi online · capture paused' : 'Pi online · no new image';
            if (!displayed) byId('empty-image').textContent = 'No image available';
            return;
        }
        if (!entry || typeof entry.url !== 'string' || !entry.url || !dateAndTime(entry.captured_at)
            || !Number.isFinite(Date.parse(entry.captured_at))) throw new Error('Invalid image data');
        const key = JSON.stringify([entry.url, entry.captured_at]);
        if (frames.displayedKey === key) imageMessage = '';
        frames.offer(key, entry.url, entry);
    }

    function updateSelects(metrics, defaults) {
        const available = new Set(metrics.map(metric => metric.id));
        const active = choices || defaults;
        selects.forEach((select, slot) => {
            const previous = Array.from(select.options).map(option => [option.value, option.label]);
            const options = [['', 'Off'], ...metrics.map(metric => [metric.id, metric.label])];
            if (JSON.stringify(previous) !== JSON.stringify(options)) {
                select.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
            }
            const value = active[slot];
            select.value = available.has(value) ? value : '';
        });
        for (const [slot, select] of selects.entries()) {
            const other = selects[1 - slot].value;
            for (const option of select.options) option.disabled = Boolean(other) && other === option.value;
        }
    }

    function drawChart(slot, series) {
        const container = byId('chart-slot-' + (slot + 1));
        const plot = container.querySelector('.plot');
        const empty = container.querySelector('.plot-empty');
        const reading = container.querySelector('.chart-value');
        const samples = (series?.points || []).map(([time, value]) => ({
            x: Date.parse(time), y: Number.isFinite(value) ? value : null, capturedAt: time,
        })).filter(point => Number.isFinite(point.x));
        const values = samples.filter(point => point.y !== null);
        const last = values[values.length - 1];
        reading.hidden = !last;
        reading.textContent = last ? formatReading(last.y) + (series.unit ? ' ' + series.unit : '') : '';
        // Equal wall times on either side of a clock change have different UTC offsets.
        const sampleTime = point => {
            const time = dateAndTime(point.capturedAt);
            const offset = point.capturedAt.match(/[+-]\d{2}:\d{2}$/);
            return time.time + ' UTC' + (offset ? offset[0] : '');
        };
        if (last) reading.title = 'Last reading at ' + sampleTime(last);
        const visible = values.length > 0 && typeof Chart === 'function';
        plot.hidden = !visible;
        empty.hidden = !selects[slot].value || visible;
        if (!visible) {
            if (charts[slot]) charts[slot].destroy();
            charts[slot] = null;
            return;
        }
        const style = getComputedStyle(page);
        const accent = style.getPropertyValue(slot ? '--color-secondary' : '--color-primary').trim();
        const ink = style.getPropertyValue('--color-base-content').trim();
        const fontSize = Math.max(14, Math.round(parseFloat(getComputedStyle(document.documentElement).fontSize) * .9));
        const now = cameraNow();
        const dataset = {
            label: series.label, data: samples, borderColor: accent, backgroundColor: accent,
            borderWidth: 1.7, pointRadius: samples.length < 3 ? 2 : 0, pointHitRadius: 8, spanGaps: false,
        };
        const options = {
            responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
            plugins: { legend: {display: false}, tooltip: { callbacks: {
                title: items => sampleTime(items[0].raw),
                label: context => formatReading(context.parsed.y) + (series.unit ? ' ' + series.unit : ''),
            } } },
            scales: {
                x: { type: 'linear', min: now - 7200000, max: now, grid: {display: false},
                    afterBuildTicks: axis => {
                        const ticks = axis.chart.width < 185 ? [axis.min, axis.max] : [axis.min, axis.min + 3600000, axis.max];
                        axis.ticks = ticks.map(value => ({value}));
                    },
                    ticks: { color: ink, font: {size: fontSize}, align: 'inner', autoSkip: false,
                        maxRotation: 0, callback: value => localTime(value) } },
                y: { ticks: { color: ink, font: {size: fontSize}, maxTicksLimit: 3, callback: value => formatReading(value) },
                    grid: {color: style.getPropertyValue('--line').trim()},
                    title: {display: false} },
            },
        };
        if (charts[slot]) {
            charts[slot].data.datasets = [dataset];
            charts[slot].options = options;
            charts[slot].update('none');
        } else {
            charts[slot] = new Chart(plot.querySelector('canvas'), {type: 'line', data: {datasets: [dataset]}, options});
        }
    }

    function showHistory(payload) {
        updateSelects(payload.metrics, payload.defaults);
        selects.forEach((select, slot) => drawChart(slot, payload.series.find(series => series.id === select.value)));
    }

    function updateClock(payload) {
        const timestamp = Date.parse(payload.now);
        if (!Number.isFinite(timestamp)) throw new Error('Invalid server time');
        if (!formats || formats.zone !== payload.time_zone) formats = clockFormats(payload.time_zone);
        clock = {timestamp, syncedAt: performance.now(), offset: payload.offset_minutes || 0};
    }

    function serviceError(issue, code, details) {
        if (issue === 'login') return 'Sign in again to view camera data';
        if (issue === 'forbidden') return 'Access to camera data denied';
        if (details) return 'Could not update twilight, moon or history data.';
        if (issue === 'network') return 'Lost connection to the Pi';
        if (issue === 'timeout') return 'Pi response timed out · retrying';
        if (issue === 'server') return 'Pi online · image service returned HTTP ' + code;
        return 'Pi online · unexpected response from the image service';
    }

    const imagePoll = new LiveJsonPoll(() => {
        const url = new URL(page.dataset.endpoint, document.baseURI);
        url.searchParams.set('image_only', '1');
        return url;
    }, 2000, payload => {
        updateClock(payload);
        capturePaused = payload.capture_paused === true;
        updateImage(payload.image);
        imageServiceMessage = '';
        tick();
    }, (issue, code) => {
        imageServiceMessage = serviceError(issue, code, false);
        if (!displayed) byId('empty-image').textContent = 'Image unavailable';
        updateStatus();
    });

    const detailPoll = new LiveJsonPoll(() => {
        const url = new URL(page.dataset.endpoint, document.baseURI);
        if (choices) {
            const active = choices.filter(Boolean);
            for (const id of active.length ? active : ['none']) url.searchParams.append('metric', id);
        }
        return url;
    }, interval, payload => {
        if (!payload?.astronomy || !Array.isArray(payload.metrics) || !Array.isArray(payload.series)
            || !Array.isArray(payload.defaults)) throw new Error('Invalid detail data');
        if (!clock) updateClock(payload);
        const astronomy = payload.astronomy;
        for (const id of eventNames) showEvent(id, astronomy[id]);
        const phase = [astronomy.moon_phase];
        if (Number.isFinite(astronomy.moon_illumination)) phase.push(number.format(astronomy.moon_illumination) + '%');
        byId('moon-phase').textContent = phase.filter(Boolean).join(' · ') || '–';
        showHistory(payload);
        lastPayload = payload;
        detailMessage = '';
        tick();
    }, (issue, code) => {
        detailMessage = serviceError(issue, code, true);
        updateStatus();
    });

    for (const select of selects) {
        select.addEventListener('change', () => {
            choices = selects.map(control => control.value);
            try { localStorage.setItem(storageKey, JSON.stringify(choices)); } catch (_) {}
            if (lastPayload) showHistory(lastPayload);
            detailPoll.refresh();
        });
    }
    window.addEventListener('storage', event => {
        if (lastPayload && event.key?.startsWith('allsky-')) showHistory(lastPayload);
    });
    window.setInterval(tick, 1000);
    followLivePage([imagePoll, detailPoll], frames);

})();
