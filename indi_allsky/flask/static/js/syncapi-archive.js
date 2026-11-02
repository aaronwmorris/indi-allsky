(function (root) {
    'use strict';

    function formatStatus(state) {
        const scheduled = !state.active && state.enabled && state.schedule && state.schedule.settings && state.schedule.settings.enabled;
        let message = state.message || state.state || 'Idle';
        if (scheduled && ['cancelled', 'interrupted', 'failed', 'complete'].includes(state.state)) {
            // The saved run is history; the schedule now determines how to
            // continue. Keep its result without obsolete manual-start advice.
            message = 'Previous run: ' + message.replace(/ Press Sync now[^.]*\./g, '')
                .replace(' The schedule will check the receiver again.', '');
        }
        if (state.active && typeof state.scheduled === 'boolean') {
            message = (state.scheduled ? 'Scheduled run — ' : 'Manual run — ') + message;
        }
        // Every state uses the same rows. Clear unused values instead of adding
        // or removing lines as uploads, acknowledgements and errors arrive.
        const rows = {
            schedule: state.schedule ? state.schedule.message || '' : '',
            next: state.schedule && state.schedule.next_action ? state.schedule.next_action.replace('T', ' ') : '',
            run: message,
            cutoff: state.cutoff ? state.cutoff.replace('T', ' ').replace(/\.\d+/, '') : '',
            items: '', transferred: '', speed: '', file: '', progress: '', notice: '',
        };
        if (typeof state.completed === 'number') {
            rows.items = `${state.completed} of ${state.total} items completed; ${state.skipped} skipped`;
            rows.transferred = `${state.files} files, ${(state.bytes / 1048576).toFixed(1)} MiB sent`;
        }
        if (state.active && state.state === 'running') {
            rows.speed = state.rates ? `${(state.rates.bytes / 1000000).toFixed(2)} MB/s · ${state.rates.items.toFixed(2)} items/s · ${state.rates.files.toFixed(2)} files/s`
                : 'Waiting for a progress update';
        }
        if (state.active && state.upload && state.upload.total > 0) {
            const upload = state.upload;
            const percent = Math.min(100, Math.floor(upload.bytes / upload.total * 100));
            rows.file = upload.name;
            rows.progress = `${(upload.bytes / 1048576).toFixed(1)} of ${(upload.total / 1048576).toFixed(1)} MiB (${percent}%)`;
            if (upload.bytes >= upload.total) rows.notice = 'Waiting for the receiver to acknowledge this file.';
        }
        if (state.cancel_requested) rows.notice = 'Cancellation requested; waiting for the upload or current network operation to stop.';
        if (!state.enabled) rows.notice = 'Enable Sync API, select Archive sync, then save and apply.';
        return rows;
    }

    function selectedTypes(document) {
        return Array.from(document.getElementById('syncapi-run-types').querySelectorAll('input:checked'), input => input.value);
    }

    function schedulePayload(document) {
        const minutes = id => {
            const value = document.getElementById(id).value.trim();
            return value ? Number(value) : null;
        };
        return {enabled: document.getElementById('syncapi-run-schedule-enabled').checked,
            interval: minutes('syncapi-run-schedule-interval'), delay: minutes('syncapi-run-schedule-delay'),
            upload_limit: Number(document.getElementById('syncapi-run-upload-limit').value),
            types: selectedTypes(document)};
    }

    function mount(panel, document, fetcher, schedule) {
        const start = document.getElementById('syncapi-run-start');
        const cancel = document.getElementById('syncapi-run-cancel');
        const choices = document.getElementById('syncapi-run-types');
        const output = document.getElementById('syncapi-run-status');
        const statusFields = output.querySelectorAll('[data-sync-status]');
        const error = document.getElementById('syncapi-run-error');
        const controls = document.getElementById('syncapi-run-schedule-controls');
        const enabled = document.getElementById('syncapi-run-schedule-enabled');
        let state = {};
        let commandPending = false;
        let requestRevision = 0;
        let commandError = '';
        let pollError = '';

        function render(value) {
            state = value;
            // The server renders saved form values. Polling only updates
            // progress, never unsaved timing edits or one-off media choices.
            // Scheduler and task status are read separately; either can report
            // a run first while the scheduler hands it to the transfer worker.
            start.disabled = commandPending || !value.enabled || value.active ||
                Boolean(value.schedule && value.schedule.state === 'running');
            cancel.disabled = commandPending || !value.active || value.cancel_requested;
            choices.disabled = commandPending || value.active;
            controls.disabled = commandPending || value.active;
            const rows = formatStatus(value);
            for (const field of statusFields) {
                const content = rows[field.dataset.syncStatus];
                if (field.textContent !== content) field.textContent = content;
                field.title = content;
            }
            error.textContent = commandError || pollError;
            error.title = error.textContent;
        }

        async function request(payload) {
            const unavailable = (reason, response) => new Error(
                (payload ? 'Could not confirm the synchronization request' : 'Could not refresh synchronization status') +
                (response && response.status ? ` (HTTP ${response.status})` : '') + `: ${reason}. ` +
                (payload ? 'Check the refreshed status before trying again.' : 'Showing the last known status; retrying automatically.'));
            const options = {credentials: 'same-origin', cache: 'no-store'};
            if (payload) {
                options.method = 'POST';
                options.headers = {'Content-Type': 'application/json', 'X-CSRFToken': panel.dataset.csrf};
                options.body = JSON.stringify(payload);
            }
            let response;
            try {
                response = await fetcher(panel.dataset.url, options);
            } catch (exception) {
                throw unavailable('connection interrupted');
            }
            if (response.redirected) throw new Error('The synchronization request was redirected. Reload this page and sign in if prompted.');
            if (response.status === 401 || response.status === 403) {
                throw new Error(`Access to synchronization controls was denied (HTTP ${response.status}). Reload this page and sign in with an administrator account.`);
            }
            let data;
            try {
                data = await response.json();
            } catch (exception) {
                throw unavailable('the server returned an unreadable response', response);
            }
            if (!response.ok) {
                throw typeof (data && data.error) === 'string' ? new Error(data.error) : unavailable('request rejected', response);
            }
            if (!data || typeof data.active !== 'boolean' || typeof data.enabled !== 'boolean') {
                throw unavailable('the server returned an invalid status', response);
            }
            return data;
        }

        async function refresh(payload) {
            // Polls leave the controls usable. A command can overtake an older
            // poll; its revision prevents that poll from restoring stale state
            // or errors. A good poll clears only polling errors; rejected user
            // actions stay visible until the next command.
            if (commandPending) return;
            const revision = ++requestRevision;
            if (payload) {
                commandPending = true;
                commandError = '';
                pollError = '';
                render(state);
            }
            try {
                const value = await request(payload);
                if (revision === requestRevision) {
                    state = value;
                    pollError = '';
                    if (payload && payload.action === 'cancel' && value.schedule && value.scheduled && value.task_id === payload.task_id) {
                        enabled.checked = value.schedule.settings.enabled;
                    }
                }
            } catch (exception) {
                if (revision === requestRevision) {
                    if (payload) commandError = exception.message;
                    else pollError = exception.message;
                }
            } finally {
                if (revision === requestRevision) {
                    commandPending = false;
                    render(state);
                }
            }
        }

        start.addEventListener('click', function () {
            const types = selectedTypes(document);
            if (!types.length) {
                commandError = 'Select at least one media type.';
                error.textContent = commandError;
                return;
            }
            return refresh({action: 'start', types: types,
                upload_limit: Number(document.getElementById('syncapi-run-upload-limit').value)});
        });
        cancel.addEventListener('click', function () {
            return refresh({action: 'cancel', task_id: state.task_id});
        });
        // A successful configuration save should not wait for the next poll.
        document.addEventListener('indi-allsky:config-saved', function () { return refresh(); });

        async function poll() {
            // This endpoint reads the sender's saved status; polling never
            // contacts the receiver. Only button handlers send commands.
            await refresh();
            schedule(poll, 5000);
        }
        return poll();
    }

    if (typeof module !== 'undefined' && module.exports) module.exports = {formatStatus, mount, schedulePayload};
    if (root.document) {
        root.indiAllskySync = {schedulePayload};
        const panel = root.document.getElementById('syncapi-run-panel');
        if (panel) mount(panel, root.document, root.fetch.bind(root), root.setTimeout.bind(root));
    }
})(typeof window === 'undefined' ? globalThis : window);
