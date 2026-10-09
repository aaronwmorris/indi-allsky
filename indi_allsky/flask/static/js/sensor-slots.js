(() => {
    'use strict';
    const list = document.getElementById('sensor-slot-list');
    if (!list) return;
    const cards = [...list.querySelectorAll('[data-sensor-slot]')];
    const add = document.getElementById('add-sensor-slot');
    const status = document.getElementById('sensor-slot-status');
    const counts = JSON.parse(list.dataset.sensorCounts);
    const field = (card, name) => card.querySelector('[id="TEMP_SENSOR__' + card.dataset.sensorSlot + '_' + name + '"]');
    const update = () => {
        add.disabled = cards.every(card => !card.hidden);
        add.textContent = add.disabled ? 'All 26 sensor slots added' : 'Add sensor';
    };
    list.addEventListener('sensor-errors', update);
    const availableSlot = (card, count) => {
        const used = new Set();
        cards.filter(other => other !== card && !other.hidden).forEach(other => {
            const start = Number(field(other, 'USER_VAR_SLOT').value.replace('sensor_user_', ''));
            const size = counts[field(other, 'CLASSNAME').value] ?? 1;
            for (let offset = 0; offset < size; offset++) used.add(start + offset);
        });
        const fits = start => start >= 10 && start + count <= 60 &&
            Array.from({length: count}, (_, offset) => start + offset).every(index => !used.has(index));
        const current = Number(field(card, 'USER_VAR_SLOT').value.replace('sensor_user_', ''));
        if (fits(current)) return 'sensor_user_' + current;
        for (let start = 10; start + count <= 60; start++) {
            if (fits(start)) {
                return 'sensor_user_' + start;
            }
        }
        return null;
    };
    add.addEventListener('click', () => {
        const card = cards.find(candidate => candidate.hidden);
        if (!card) return;
        card.hidden = false;
        card.querySelector('input[type="checkbox"]').checked = true;
        const slot = availableSlot(card, 1);
        if (slot) field(card, 'USER_VAR_SLOT').value = slot;
        status.textContent = 'Sensor ' + card.dataset.sensorSlot + ' added. Select a driver and save to enable it.';
        field(card, 'CLASSNAME').focus();
        update();
    });
    list.addEventListener('click', event => {
        const remove = event.target.closest('[data-remove-sensor]');
        if (!remove) return;
        event.stopPropagation();
        const card = remove.closest('[data-sensor-slot]');
        const classname = field(card, 'CLASSNAME');
        classname.value = '';
        classname.dispatchEvent(new Event('change', {bubbles: true}));
        card.hidden = true;
        status.textContent = 'Sensor ' + card.dataset.sensorSlot + ' removed. Save to apply the change.';
        update();
        add.focus();
    });
    list.addEventListener('change', event => {
        const card = event.target.closest('[data-sensor-slot]');
        if (!card || event.target !== field(card, 'CLASSNAME') || !event.target.value) return;
        const slot = availableSlot(card, counts[event.target.value]);
        if (slot) {
            field(card, 'USER_VAR_SLOT').value = slot;
        } else {
            status.textContent = 'Not enough free reading slots for this driver. Adjust initial slots or remove another sensor before saving.';
        }
    });
    cards.filter(card => !card.hidden).forEach(card => {
        card.querySelector('input[type="checkbox"]').checked = false;
    });
    update();
})();
