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
            const close = document.createElement('button'); close.type = 'button'; close.className = 'chart-overlay-close';
            close.title = 'Dismiss charts'; close.setAttribute('aria-label', 'Dismiss browser chart block');
            const icon = document.createElement('i'); icon.className = 'tw:icon-[lucide--x] tw:w-4 tw:h-4'; icon.setAttribute('aria-hidden', 'true');
            close.append(icon);
            close.addEventListener('click', () => {
                this.dismissed = true; root.hidden = true; clearTimeout(this.timer); this.controller?.abort(); ++this.generation;
                this.panels.forEach(panel => { panel.chart.destroy(); panel.element.remove(); });
                this.panels.clear(); root.setAttribute('aria-busy', 'false');
            });
            root.prepend(close);
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
                if (image && image.width > 0 && image.height > 0 && media) {
                    const rect = media.getBoundingClientRect();
                    const scale = Math.min(rect.width / image.width, rect.height / image.height);
                    const width = Math.min((parseFloat(root.style.getPropertyValue('--chart-overlay-width')) || 260) * 2.25, image.width - 32);
                    if (scale > 0 && (root.style.getPropertyValue('--chart-overlay-scale') !== String(scale) || root.style.getPropertyValue('--chart-overlay-cell-width') !== width + 'px')) {
                        root.style.setProperty('--chart-overlay-scale', scale);
                        root.style.setProperty('--chart-overlay-cell-width', width + 'px');
                        this.panels.forEach(panel => panel.chart.resize());
                    }
                }
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
                if (event.button !== 0 || !handle || event.target.closest('button')) return;
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
                if (!event.target.closest('.chart-panel-header') || event.target.closest('button')) return;
                manual = null; root.style.removeProperty('left'); root.style.removeProperty('right');
                try { localStorage.removeItem(storageKey); } catch (error) {}
                position();
            });
            root.addEventListener('keydown', event => {
                if (!event.target.closest('.chart-panel-header') || event.target.closest('button') || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
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
            this.options.definitions = definitions;
            const wanted = [...definitions.map(definition => definition.id), 'histogram'].filter(identifier => this.options.ids.includes(identifier));
            if (this.options.compact) this.root.style.setProperty('--chart-overlay-columns', wanted.length > 1 ? '2' : '1');
            this.panels.forEach((panel, identifier) => {
                if (!wanted.includes(identifier)) { panel.chart.destroy(); panel.element.remove(); this.panels.delete(identifier); }
            });
            wanted.forEach((identifier, index) => {
                const definition = definitions.find(item => item.id === identifier) || {id: 'histogram', label: 'Image histogram', min: 0};
                const bounds = this.options.axisLimits?.[identifier] || {};
                const suggestedMin = ['detection', 'histogram'].includes(identifier) ? definition.min ?? 0 : undefined;
                let panel = this.panels.get(identifier);
                if (!panel) {
                    const element = document.createElement('article'); element.className = 'chart-panel'; element.dataset.chartId = identifier;
                    const header = document.createElement('div'); header.className = 'chart-panel-header';
                    if (this.options.compact) { header.tabIndex = 0; header.title = 'Drag to move charts; double-click to reset'; }
                    const title = document.createElement('h2'); const value = document.createElement('span'); value.className = 'chart-value'; value.textContent = '--';
                    header.append(title, value);
                    const plot = document.createElement('div'); plot.className = 'chart-plot';
                    const canvas = document.createElement('canvas'); canvas.setAttribute('role', 'img');
                    const empty = document.createElement('span'); empty.className = 'chart-no-data'; empty.textContent = this.options.compact ? 'No data' : 'No readings';
                    plot.append(canvas, empty); element.append(header, plot); this.grid.append(element);
                    const color = this.options.compact ? '#38bdf8' : colors[index % colors.length];
                    const datasets = identifier === 'histogram' ? ['red', 'green', 'blue', 'gray'].map((label, colorIndex) => ({label, data: [], borderColor: ['#df827b', '#84b96b', '#69addb', '#a6b1b6'][colorIndex], pointRadius: 0})) : [{label: definition.label, data: [], borderColor: color, backgroundColor: color, fill: false, pointRadius: this.options.compact ? 2.7 * 100 / 72 / 2 : 3, pointBorderWidth: this.options.compact ? 1.8 * 100 / 72 : undefined, pointHitRadius: 8, borderWidth: this.options.compact ? 1.8 * 100 / 72 : undefined, tension: this.options.compact ? 0 : .1, spanGaps: false}];
                    const foreground = this.options.compact ? '#b9c4c4' : getComputedStyle(document.body).color;
                    const temporal = this.options.compact && identifier !== 'histogram';
                    const axisFont = this.options.compact ? {size: 11 * 100 / 72} : undefined;
                    const chart = new Chart(canvas, {type: identifier === 'detection' ? 'bar' : 'line', data: {datasets},
                        plugins: this.options.compact ? [{id: 'imageChartScale', beforeUpdate: chart => {
                            const scale = parseFloat(this.root.style.getPropertyValue('--chart-overlay-scale')) || 1;
                            chart.options.scales.x.ticks.font.size = chart.options.scales.y.ticks.font.size = 11 * 100 / 72 * scale;
                            chart.options.scales.x.border.width = chart.options.scales.y.border.width = .4 * 100 / 72 * scale;
                            chart.options.scales.y.grid.lineWidth = .5 * 100 / 72 * scale;
                            if (identifier !== 'histogram') chart.data.datasets.forEach(dataset => {
                                dataset.borderWidth = dataset.pointBorderWidth = 1.8 * 100 / 72 * scale;
                                dataset.pointRadius = 2.7 * 100 / 72 / 2 * scale;
                            });
                        }}] : [], options: {
                        responsive: true, maintainAspectRatio: false, animation: false,
                        interaction: {mode: 'index', intersect: false},
                        plugins: {legend: {display: identifier === 'histogram', labels: {color: foreground, boxWidth: 10}}},
                        scales: {
                            x: {display: true, type: temporal ? 'linear' : 'category', min: temporal ? 0 : undefined, max: temporal ? (this.options.historySeconds || 900) : undefined, afterBuildTicks: temporal ? axis => {
                                const scale = parseFloat(this.root.style.getPropertyValue('--chart-overlay-scale')) || 1;
                                const count = Math.max(2, Math.floor(axis.width / (80 * scale)) + 1);
                                axis.ticks = Array.from({length: count}, (_, index) => ({value: index * axis.max / (count - 1)}));
                            } : undefined, border: this.options.compact ? {color: '#536564', width: .4 * 100 / 72} : undefined, grid: {display: !this.options.compact, drawTicks: false, color: 'rgba(128,128,128,.12)'}, ticks: {color: foreground, autoSkip: !this.options.compact, minRotation: this.options.compact ? 0 : undefined, maxRotation: this.options.compact ? 0 : undefined, callback: temporal ? function(value) { return new Date((this.chart.$historyClock || 0) - (this.max - value) * 1000).toISOString().slice(11, 16); } : function(value) { const label = this.getLabelForValue(value); return identifier === 'histogram' ? label : String(label).slice(0, 5); }, font: axisFont}},
                            y: {display: true, beginAtZero: ['detection', 'histogram'].includes(identifier), suggestedMin, suggestedMax: identifier === 'detection' ? 1 : undefined, min: bounds.min ?? undefined, max: bounds.max ?? undefined,
                                bounds: identifier !== 'histogram' ? 'data' : undefined,
                                afterDataLimits: identifier !== 'histogram' ? axis => {
                                    let lower = Infinity, upper = -Infinity;
                                    axis.chart.data.datasets.forEach(dataset => dataset.data.forEach(point => {
                                        if (Number.isFinite(point?.y)) { lower = Math.min(lower, point.y); upper = Math.max(upper, point.y); }
                                    }));
                                    if (!Number.isFinite(lower)) return;
                                    if (identifier === 'detection') { lower = Math.min(lower, 0); upper = Math.max(upper, 1); }
                                    const stickyZero = identifier === 'detection' && lower === 0 && upper > 0;
                                    if (lower === upper) { const span = Math.abs(lower) * .05 || .05; lower -= span; upper += span; }
                                    const padding = (upper - lower) * .05;
                                    lower -= padding; upper += padding;
                                    if (stickyZero) lower = 0;
                                    if (Number.isFinite(axis.options.suggestedMin)) lower = Math.min(lower, axis.options.suggestedMin);
                                    if (Number.isFinite(axis.options.min)) {
                                        lower = axis.options.min;
                                        if (!Number.isFinite(axis.options.max) && upper <= lower) upper = lower + Math.max(Math.abs(lower) * .05, 1);
                                    }
                                    if (Number.isFinite(axis.options.max)) {
                                        upper = axis.options.max;
                                        if (!Number.isFinite(axis.options.min) && lower >= upper) lower = upper - Math.max(Math.abs(upper) * .05, 1);
                                    }
                                    axis.min = lower; axis.max = upper;
                                } : undefined,
                                afterBuildTicks: this.options.compact ? axis => { axis.ticks = Array.from({length: 5}, (_, index) => ({value: axis.min + (axis.max - axis.min) * index / 4})); } : undefined,
                                border: this.options.compact ? {color: '#536564', width: .4 * 100 / 72} : undefined,
                                grid: {color: this.options.compact ? 'rgba(203,213,211,.17)' : 'rgba(128,128,128,.12)', lineWidth: this.options.compact ? .5 * 100 / 72 : undefined}, ticks: {color: foreground, autoSkip: !this.options.compact, maxTicksLimit: this.options.compact ? 5 : undefined, font: axisFont}}
                        }
                    }});
                    panel = {element, title, value, chart, canvas}; this.panels.set(identifier, panel);
                }
                panel.title.textContent = definition.label; panel.title.title = definition.label; panel.canvas.setAttribute('aria-label', definition.label + ' history');
                panel.chart.options.scales.y.suggestedMin = suggestedMin;
                panel.chart.options.scales.y.min = bounds.min ?? undefined; panel.chart.options.scales.y.max = bounds.max ?? undefined;
                this.grid.append(panel.element);
            });
            let empty = this.root.querySelector('.chart-stream-empty');
            if (!wanted.length && !empty) { empty = document.createElement('p'); empty.className = 'chart-stream-empty'; empty.textContent = 'No charts selected'; this.grid.append(empty); }
            if (wanted.length) empty?.remove();
        }
        async refresh() {
            clearTimeout(this.timer); this.controller?.abort();
            if (document.hidden || this.dismissed || !this.panels.size) return;
            const generation = ++this.generation; this.controller = new AbortController();
            this.status.textContent = this.options.compact ? '' : 'Updating'; this.root.setAttribute('aria-busy', 'true');
            const parameters = new URLSearchParams({camera_id: this.options.cameraId, limit_s: this.history?.value || this.options.historySeconds || 900, timestamp: this.options.timestamp || 0, series: this.options.ids.filter(identifier => identifier !== 'histogram').join(','), histogram: this.options.ids.includes('histogram') ? '1' : '0'});
            if (this.options.compact) parameters.set('image_chart', '1');
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
                        if (this.options.compact) {
                            const history = Number(parameters.get('limit_s'));
                            const latest = points.at(-1);
                            const clock = value => value.split(':').map(Number).reduce((seconds, part) => seconds * 60 + part, 0);
                            const endClock = latest ? clock(latest.x) : 0;
                            panel.chart.$historyClock = endClock * 1000;
                            panel.chart.options.scales.x.max = history;
                            panel.chart.data.datasets[0].data = points.map(point => ({
                                x: history - (latest.timestamp - point.timestamp),
                                y: point.y,
                            }));
                        } else {
                            panel.chart.data.labels = points.map(point => point.x);
                            panel.chart.data.datasets[0].data = points;
                        }
                        const reading = points.at(-1)?.y;
                        panel.value.textContent = Number.isFinite(reading) ? new Intl.NumberFormat(undefined, this.options.compact ? {maximumSignificantDigits: 4, useGrouping: false} : {maximumFractionDigits: 1}).format(reading) : this.options.compact ? '---' : '--';
                        panel.element.dataset.empty = String(!points.some(point => Number.isFinite(point.y)));
                    }
                    panel.chart.update('none');
                });
                this.status.textContent = data.message || (this.options.compact ? '' : 'Updated ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})); this.root.dataset.state = 'ready';
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