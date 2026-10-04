(() => {
    const colors = ['#27baa5', '#e2ac52', '#df827b', '#84b96b', '#69addb', '#d283ac'];
    class ChartStream {
        constructor(root, options) {
            this.root = root; this.options = options; this.panels = new Map(); this.generation = 0;
            this.status = root.querySelector('[data-chart-status]'); this.grid = root.querySelector('[data-chart-grid]');
            this.history = document.getElementById(options.historySelect || '');
            if (this.history) {
                try {
                    const saved = JSON.parse(localStorage.getItem('chart_settings') || '{}');
                    if ([...this.history.options].some(option => Number(option.value) === Number(saved.history_seconds))) this.history.value = saved.history_seconds;
                } catch (error) {}
                this.history.addEventListener('change', () => {
                    try { localStorage.setItem('chart_settings', JSON.stringify({history_seconds: Number(this.history.value)})); } catch (error) {}
                    this.refresh();
                });
            }
            this.reconcile(options.definitions);
            if (options.compact) this.positionOverlay();
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) { clearTimeout(this.timer); this.controller?.abort(); }
                else this.refresh();
            });
            window.addEventListener('pagehide', () => { clearTimeout(this.timer); this.controller?.abort(); });
            window.addEventListener('pageshow', event => { if (event.persisted) this.refresh(); });
            this.refresh();
        }
        positionOverlay() {
            const root = this.root;
            const stage = document.getElementById('latest-image-stage');
            const message = document.getElementById('status-overlay');
            const media = stage.querySelector('#latest-image, #canvas');
            const requestedTop = parseFloat(root.style.getPropertyValue('--chart-overlay-top')) || 0;
            const storageKey = 'chart-overlay-position:' + this.options.cameraId;
            let manual = null, drag = null, image = null;
            try {
                const saved = JSON.parse(localStorage.getItem(storageKey));
                if (saved && ['left', 'top'].every(key => Number.isFinite(saved[key]) && saved[key] >= 0 && saved[key] <= 1)) manual = saved;
            } catch (error) {}
            const limits = () => ({left: Math.max(0, stage.clientWidth - root.offsetWidth - 16), top: Math.max(0, stage.clientHeight - (root.querySelector('.chart-panel')?.offsetHeight || 110) - 16)});
            const position = () => {
                if (manual) {
                    const space = limits();
                    root.style.left = manual.left * space.left + 'px'; root.style.right = 'auto';
                    root.style.setProperty('--chart-overlay-top', manual.top * space.top + 'px');
                    return;
                }
                const messageBottom = message && getComputedStyle(message).display !== 'none' ? message.offsetTop + message.offsetHeight + 8 : 0;
                let labelBottom = 0;
                if (image && image.width > 0 && image.height > 0 && media) {
                    const rect = media.getBoundingClientRect(), stageRect = stage.getBoundingClientRect();
                    const scale = Math.min(rect.width / image.width, rect.height / image.height);
                    const bounds = (image.label_bounds || []).filter(bound => Array.isArray(bound) && bound.length === 4 && bound.every(Number.isFinite));
                    if (bounds.length) labelBottom = rect.top - stageRect.top - stage.clientTop + (rect.height - image.height * scale) / 2 + Math.max(...bounds.map(bound => bound[3])) * scale + 8;
                }
                root.style.setProperty('--chart-overlay-top', Math.min(Math.max(requestedTop, messageBottom, labelBottom), Math.max(0, stage.clientHeight - 48)) + 'px');
            };
            const move = (left, top) => {
                const space = limits();
                manual = {left: space.left ? Math.max(0, Math.min(left, space.left)) / space.left : 0, top: space.top ? Math.max(0, Math.min(top, space.top)) / space.top : 0};
                position();
            };
            const remember = () => { try { localStorage.setItem(storageKey, JSON.stringify(manual)); } catch (error) {} };
            root.addEventListener('pointerdown', event => {
                const handle = event.target.closest('.chart-panel-header');
                if (event.button !== 0 || !handle) return;
                event.preventDefault();
                drag = {id: event.pointerId, handle, x: event.clientX, y: event.clientY, left: root.offsetLeft, top: root.offsetTop};
                handle.setPointerCapture(event.pointerId); root.classList.add('is-dragging');
            });
            root.addEventListener('pointermove', event => {
                if (drag && event.pointerId === drag.id) move(drag.left + event.clientX - drag.x, drag.top + event.clientY - drag.y);
            });
            const finish = event => {
                if (!drag || event.pointerId !== drag.id) return;
                const handle = drag.handle;
                drag = null; root.classList.remove('is-dragging');
                if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
                if (manual) remember();
            };
            ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => root.addEventListener(name, finish));
            root.addEventListener('dblclick', event => {
                if (!event.target.closest('.chart-panel-header')) return;
                manual = null; root.style.removeProperty('left'); root.style.removeProperty('right');
                try { localStorage.removeItem(storageKey); } catch (error) {}
                position();
            });
            root.addEventListener('keydown', event => {
                if (!event.target.closest('.chart-panel-header') || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
                event.preventDefault();
                const step = event.shiftKey ? 1 : 10;
                move(root.offsetLeft + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0), root.offsetTop + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0));
                remember();
            });
            stage.addEventListener('chart-image-loaded', event => { image = event.detail; position(); });
            new ResizeObserver(position).observe(stage);
            if (media) new ResizeObserver(position).observe(media);
            if (message) new MutationObserver(position).observe(message, {attributes: true, childList: true, subtree: true});
            position();
        }
        reconcile(definitions) {
            const wanted = [...definitions.map(definition => definition.id), 'histogram'].filter(identifier => this.options.ids.includes(identifier));
            if (this.options.compact) this.root.style.setProperty('--chart-overlay-columns', wanted.length > 1 ? '2' : '1');
            this.panels.forEach((panel, identifier) => {
                if (!wanted.includes(identifier)) { panel.chart.destroy(); panel.element.remove(); this.panels.delete(identifier); }
            });
            wanted.forEach((identifier, index) => {
                const definition = definitions.find(item => item.id === identifier) || {id: 'histogram', label: 'Image histogram', min: 0};
                const bounds = this.options.axisLimits?.[identifier] || {};
                let panel = this.panels.get(identifier);
                if (!panel) {
                    const element = document.createElement('article'); element.className = 'chart-panel'; element.dataset.chartId = identifier;
                    const header = document.createElement('div'); header.className = 'chart-panel-header';
                    if (this.options.compact) { header.tabIndex = 0; header.title = 'Drag to move charts; double-click to reset'; }
                    const title = document.createElement('h2'); const value = document.createElement('span'); value.className = 'chart-value'; value.textContent = '--';
                    header.append(title, value);
                    const plot = document.createElement('div'); plot.className = 'chart-plot';
                    const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img');
                    const empty = document.createElement('span'); empty.className = 'chart-no-data'; empty.textContent = 'No readings';
                    plot.append(canvas, empty); element.append(header, plot); this.grid.append(element);
                    const color = this.options.compact ? '#38bdf8' : colors[index % colors.length];
                    const datasets = identifier === 'histogram' ? ['red', 'green', 'blue', 'gray'].map((label, colorIndex) => ({label, data: [], borderColor: ['#df827b', '#84b96b', '#69addb', '#a6b1b6'][colorIndex], pointRadius: 0})) : [{label: definition.label, data: [], borderColor: color, backgroundColor: color, fill: false, pointRadius: this.options.compact ? 1.8 : 3, pointHitRadius: 8, borderWidth: this.options.compact ? 1 : undefined, tension: this.options.compact ? 0 : .1, spanGaps: false}];
                    const foreground = this.options.compact ? '#bccdcc' : getComputedStyle(document.body).color;
                    const chart = new Chart(canvas, {type: identifier === 'detection' ? 'bar' : 'line', data: {datasets}, options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        interaction: {mode: 'index', intersect: false},
                        plugins: {legend: {display: identifier === 'histogram', labels: {color: foreground, boxWidth: 10}}},
                        scales: {
                            x: {display: true, afterBuildTicks: this.options.compact ? axis => { if (axis.ticks.length > 1) axis.ticks = [axis.ticks[0], axis.ticks.at(-1)]; } : undefined, grid: {display: !this.options.compact, drawTicks: false, color: 'rgba(128,128,128,.12)'}, ticks: {color: foreground, maxTicksLimit: this.options.compact ? 2 : undefined, maxRotation: this.options.compact ? 0 : undefined, font: this.options.compact ? {size: 9} : undefined}},
                            y: {display: true, beginAtZero: !this.options.compact && ['jsqm', 'stars', 'temp', 'exp', 'gain', 'histogram'].includes(identifier), suggestedMin: definition.min ?? undefined, suggestedMax: identifier === 'detection' ? 1 : undefined, min: bounds.min ?? undefined, max: bounds.max ?? undefined, grid: {color: 'rgba(128,128,128,.12)'}, ticks: {color: foreground, maxTicksLimit: this.options.compact ? 3 : undefined, font: this.options.compact ? {size: 9} : undefined}}
                        }
                    }});
                    panel = {element, title, value, chart, canvas}; this.panels.set(identifier, panel);
                }
                panel.title.textContent = definition.label; panel.canvas.setAttribute('aria-label', definition.label + ' history');
                panel.chart.options.scales.y.suggestedMin = definition.min ?? undefined;
                panel.chart.options.scales.y.min = bounds.min ?? undefined; panel.chart.options.scales.y.max = bounds.max ?? undefined;
                this.grid.append(panel.element);
            });
            let empty = this.root.querySelector('.chart-stream-empty');
            if (!wanted.length && !empty) { empty = document.createElement('p'); empty.className = 'chart-stream-empty'; empty.textContent = 'No charts selected'; this.grid.append(empty); }
            if (wanted.length) empty?.remove();
        }
        async refresh() {
            clearTimeout(this.timer); this.controller?.abort();
            if (document.hidden || !this.panels.size) return;
            const generation = ++this.generation; this.controller = new AbortController();
            this.status.textContent = 'Updating'; this.root.setAttribute('aria-busy', 'true');
            const parameters = new URLSearchParams({camera_id: this.options.cameraId, limit_s: this.history?.value || this.options.historySeconds || 900, timestamp: this.options.timestamp || 0, series: this.options.ids.filter(identifier => identifier !== 'histogram').join(','), histogram: this.options.ids.includes('histogram') ? '1' : '0'});
            try {
                const response = await fetch(this.options.url + '?' + parameters, {signal: this.controller.signal, headers: {Accept: 'application/json'}});
                if (!response.ok) throw new Error('Chart request failed');
                const data = await response.json(); if (generation !== this.generation) return;
                this.reconcile(data.chart_definitions || this.options.definitions);
                this.panels.forEach((panel, identifier) => {
                    const points = data.chart_data[identifier] || [];
                    if (identifier === 'histogram') {
                        panel.chart.data.datasets.forEach(dataset => { dataset.data = data.chart_data.histogram?.[dataset.label] || []; });
                        panel.element.dataset.empty = String(!panel.chart.data.datasets.some(dataset => dataset.data.length)); panel.value.textContent = '';
                    } else {
                        panel.chart.data.datasets[0].data = points;
                        const reading = points.at(-1)?.y;
                        panel.value.textContent = Number.isFinite(reading) ? new Intl.NumberFormat(undefined, {maximumFractionDigits: 1}).format(reading) : '--';
                        panel.element.dataset.empty = String(!points.some(point => Number.isFinite(point.y)));
                    }
                    panel.chart.update('none');
                });
                this.status.textContent = data.message || 'Updated ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); this.root.dataset.state = 'ready';
            } catch (error) {
                if (error.name !== 'AbortError') { this.status.textContent = 'Charts unavailable'; this.root.dataset.state = 'error'; }
            } finally {
                if (generation === this.generation) {
                    this.root.setAttribute('aria-busy', 'false');
                    if (!this.options.timestamp && !document.hidden) this.timer = setTimeout(() => this.refresh(), Math.max(5000, this.options.refreshInterval || 15000));
                }
            }
        }
    }
    function init() {
        document.querySelectorAll('[data-chart-stream]').forEach(root => {
            const options = JSON.parse(document.getElementById(root.dataset.chartOptions).textContent); new ChartStream(root, options);
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();