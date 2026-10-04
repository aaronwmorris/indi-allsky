(() => {
    function initEditor(root) {
        const field = document.getElementById('CHARTS__CONFIG');
        const settings = JSON.parse(field.value);
        const options = JSON.parse(document.getElementById('chart-editor-options').textContent);
        const list = root.querySelector('[data-chart-list]');
        const error = document.getElementById('CHARTS__CONFIG-error');
        const inputClasses = 'tw:input tw:input-bordered tw:input-sm tw:bg-base-100';
        const selectClasses = 'tw:select tw:select-bordered tw:select-sm tw:bg-base-100';
        const checkboxClasses = 'tw:checkbox tw:checkbox-sm tw:checkbox-primary';
        settings.AXIS_LIMITS ||= {};
        function save() {
            field.value = JSON.stringify(settings);
            root.querySelector('[data-chart-count]').textContent = settings.CUSTOM.length + ' custom charts';
            root.querySelector('[data-chart-add]').disabled = settings.CUSTOM.length >= options.maximum;
            field.dispatchEvent(new Event('change', {bubbles: true}));
        }
        function selection(key, identifier, checked) {
            settings[key] = settings[key].filter(value => value !== identifier);
            if (checked) settings[key].push(identifier);
            save();
        }
        function label(text, input, className = '') {
            const wrapper = document.createElement('label');
            wrapper.className = className;
            const caption = document.createElement('span'); caption.textContent = text;
            wrapper.append(caption, input); return wrapper;
        }
        function check(text, key, identifier) {
            const input = document.createElement('input');
            input.type = 'checkbox'; input.className = checkboxClasses;
            input.checked = settings[key].includes(identifier);
            input.addEventListener('change', () => selection(key, identifier, input.checked));
            return label(text, input, 'chart-check');
        }
        function button(title, icon, callback, disabled = false) {
            const element = document.createElement('button');
            element.type = 'button'; element.className = 'chart-icon-button';
            element.title = title; element.setAttribute('aria-label', title); element.disabled = disabled;
            const glyph = document.createElement('i'); glyph.className = 'tw:icon-[lucide--' + icon + '] tw:w-4 tw:h-4';
            element.append(glyph); element.addEventListener('click', callback); return element;
        }
        function axisControl(identifier, name) {
            const details = document.createElement('details'); details.className = 'chart-axis-control';
            details.dataset.axisId = identifier;
            const summary = document.createElement('summary'); summary.className = 'chart-icon-button';
            summary.title = 'Y-axis limits'; summary.setAttribute('aria-label', 'Y-axis limits for ' + name);
            const icon = document.createElement('i'); icon.className = 'tw:icon-[lucide--sliders] tw:w-4 tw:h-4'; summary.append(icon);
            const popup = document.createElement('div'); popup.className = 'chart-axis-popup';
            const heading = document.createElement('strong'); heading.textContent = 'Y-axis limits'; popup.append(heading);
            const inputs = document.createElement('div'); inputs.className = 'chart-axis-inputs';
            ['min', 'max'].forEach(key => {
                const input = document.createElement('input'); input.type = 'number'; input.step = 'any';
                input.className = inputClasses; input.placeholder = 'Auto'; input.dataset.axisLimit = key;
                input.value = settings.AXIS_LIMITS[identifier]?.[key] ?? '';
                input.addEventListener('input', () => {
                    if (input.validity.badInput) return;
                    const bounds = settings.AXIS_LIMITS[identifier] || {min: null, max: null};
                    bounds[key] = input.value === '' ? null : input.valueAsNumber;
                    if (bounds.min === null && bounds.max === null) delete settings.AXIS_LIMITS[identifier];
                    else settings.AXIS_LIMITS[identifier] = bounds;
                    summary.dataset.custom = String(Boolean(settings.AXIS_LIMITS[identifier])); save();
                });
                inputs.append(label(key === 'min' ? 'Minimum' : 'Maximum', input));
            });
            popup.append(inputs); details.append(summary, popup);
            summary.dataset.custom = String(Boolean(settings.AXIS_LIMITS[identifier]));
            details.addEventListener('toggle', () => {
                if (!details.open) return;
                root.querySelectorAll('.chart-axis-control[open]').forEach(other => { if (other !== details) other.open = false; });
                const anchor = summary.getBoundingClientRect();
                popup.style.left = Math.max(16, Math.min(anchor.left, innerWidth - popup.offsetWidth - 16)) + 'px';
                popup.style.top = Math.max(16, Math.min(anchor.bottom + 6, innerHeight - popup.offsetHeight - 16)) + 'px';
            });
            details.addEventListener('keydown', event => { if (event.key === 'Escape') { details.open = false; summary.focus(); } });
            return details;
        }
        root.addEventListener('click', event => {
            root.querySelectorAll('.chart-axis-control[open]').forEach(details => { if (!details.contains(event.target)) details.open = false; });
        });
        root.closest('form')?.addEventListener('submit', event => {
            const invalid = [...root.querySelectorAll('[data-axis-limit]')].find(input => input.validity.badInput);
            if (invalid) {
                event.preventDefault(); event.stopImmediatePropagation();
                invalid.closest('details').open = true; invalid.focus();
                error.textContent = 'Enter a numeric chart axis limit or leave it automatic.'; error.style.display = 'block';
            }
        }, true);
        function render() {
            list.replaceChildren();
            settings.CUSTOM.forEach((definition, index) => {
                const row = document.createElement('div'); row.className = 'chart-editor-row'; row.dataset.chartId = definition.id;
                const name = document.createElement('input');
                name.type = 'text'; name.className = inputClasses; name.maxLength = 80; name.value = definition.label; name.placeholder = 'Sensor name';
                name.addEventListener('input', () => { definition.label = name.value; save(); });
                const source = document.createElement('select'); source.className = selectClasses;
                Object.entries(options.sources).forEach(([group, choices]) => {
                    const optgroup = document.createElement('optgroup'); optgroup.label = group;
                    choices.forEach(([value, text]) => {
                        const choice = document.createElement('option'); choice.value = value; choice.textContent = text; optgroup.append(choice);
                    });
                    source.append(optgroup);
                });
                source.value = definition.source;
                source.addEventListener('change', () => { definition.source = source.value; save(); });
                const actions = document.createElement('div'); actions.className = 'chart-row-actions';
                function move(direction) {
                    const destination = index + direction;
                    [settings.CUSTOM[index], settings.CUSTOM[destination]] = [settings.CUSTOM[destination], settings.CUSTOM[index]];
                    render(); save(); list.querySelector('[data-chart-id="' + definition.id + '"] input').focus();
                }
                actions.append(button('Move chart up', 'arrow-up-circle', () => move(-1), index === 0),
                    button('Move chart down', 'chevron-down', () => move(1), index === settings.CUSTOM.length - 1),
                    button('Remove chart', 'trash-2', () => {
                        settings.CUSTOM.splice(index, 1);
                        settings.VISIBLE_IDS = settings.VISIBLE_IDS.filter(value => value !== definition.id);
                        settings.OVERLAY_IDS = settings.OVERLAY_IDS.filter(value => value !== definition.id);
                        delete settings.AXIS_LIMITS[definition.id];
                        render(); save();
                    }));
                row.append(label('Name', name), label('Source', source, 'chart-source'), axisControl(definition.id, definition.label || definition.source),
                    check('History', 'VISIBLE_IDS', definition.id), check('On image', 'OVERLAY_IDS', definition.id), actions);
                list.append(row);
            });
        }
        const builtinList = root.querySelector('[data-builtin-charts]');
        [...options.builtins, {id: 'histogram', label: 'Image histogram'}].forEach(definition => {
            const row = document.createElement('div'); row.className = 'chart-builtin-row';
            const name = document.createElement('span'); name.textContent = definition.label;
            row.append(name, check('History', 'VISIBLE_IDS', definition.id));
            if (definition.id !== 'histogram') row.append(check('On image', 'OVERLAY_IDS', definition.id), axisControl(definition.id, definition.label));
            builtinList.append(row);
        });
        root.querySelector('[data-chart-add]').addEventListener('click', () => {
            if (settings.CUSTOM.length >= options.maximum) return;
            const identifier = 'custom_' + Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16).padStart(8, '0')).join('_');
            settings.CUSTOM.push({id: identifier, source: 'sensor_user_10', label: '', min: null});
            settings.VISIBLE_IDS.push(identifier); render(); save(); list.lastElementChild.querySelector('input').focus();
        });
        root.querySelectorAll('[data-chart-preference]').forEach(input => {
            const key = input.dataset.chartPreference; input.value = settings[key];
            if (input.tagName === 'SELECT' && input.value === '') {
                const choice = new Option(settings[key] + ' seconds', settings[key], true, true); input.append(choice);
            }
            input.addEventListener('change', () => { settings[key] = Number(input.value); save(); });
        });
        render(); save();
    }
    function init() { document.querySelectorAll('[data-chart-editor]').forEach(initEditor); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();