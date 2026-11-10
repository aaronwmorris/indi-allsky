'use strict';

(() => {
    const byId = id => document.getElementById(id);
    const page = byId('live-view');
    const sidebar = byId('sidebar-live-status');
    if (!page && !sidebar?.dataset.endpoint) return;

    // Keep the summary short; the status section also provides the appropriate recovery action.
    const reasons = {
        no_camera: ['no camera', 'No camera selected.'],
        paused: ['capture paused', 'Capture is paused.', 'settings'],
        capture_time_unknown: ['capture time uncertain', 'The camera timestamp for this image is uncertain.'],
        daytime_disabled: ['daytime capture off', 'Daytime capture is disabled.', 'settings'],
        daytime_unsaved_remote: ['daytime saving off', 'This camera does not save daytime images.'],
        local_file_restricted: ['access restricted', 'This image is restricted to the local network.'],
        archive_unavailable: ['archive unavailable', 'Archive unavailable. Capture will resume when storage is writable.', 'services'],
        archive_full: ['archive full', 'Archive full. Free up space to resume capture.', 'services'],
        archive_readonly: ['archive read-only', 'Archive is read-only. Restore write access to resume capture.', 'services'],
        capture_recovering: ['recovering capture', 'Automatic capture recovery is in progress.', 'services'],
        processing_recovering: ['recovering processing', 'Automatic image processing recovery is in progress.', 'services'],
        capture_retrying: ['retrying capture', 'The camera is automatically retrying capture.', 'services'],
        capture_backoff: ['capture retry pending', 'Capture recovery is waiting before its next attempt.', 'services'],
        processing_backoff: ['processing retry pending', 'Image processing recovery is waiting before its next attempt.', 'services'],
        processing: ['processing image', 'A captured frame is waiting to be published.', 'retry'],
        awaiting_frame: ['waiting for capture', 'Waiting for the next camera frame.', 'retry'],
        no_recent_image: ['no recent image', 'No recent image is available.', 'retry'],
        capture_status_stale: ['capture status stale', 'Capture status has not been updated.', 'services'],
        focus_waiting: ['waiting for focus', 'Waiting for a focus image.', 'retry'],
    };
    const delayedReasons = new Set(['processing', 'awaiting_frame', 'no_recent_image', 'capture_status_stale', 'focus_waiting']);
    // A successful HTTP response doesn't tell us whether acquisition is running.
    const stationIssues = {
        no_indiserver: ['The capture service cannot reach the INDI server.', 'services'],
        no_camera: ['The capture service could not find a camera.', 'services'],
        camera_error: ['The capture service reports a camera error.', 'services'],
        stopped: ['The capture service is stopped.', 'services'],
        stopping: ['The capture service is stopping.'],
        down: ['The capture service has not updated its watchdog.', 'services'],
        paused: ['Capture is paused.', 'settings'],
        inactive: ['Another local camera is selected for capture.'],
        unknown: ['The station has not reported a known capture state.', 'services'],
    };
    const requestLabels = {
        login: 'SIGN IN REQUIRED', forbidden: 'ACCESS DENIED', timeout: 'WEB TIMEOUT',
        network: 'CONNECTION LOST', invalid: 'STATUS UNAVAILABLE', server: 'WEB ERROR',
    };
    const requestErrors = {
        login: ['sign-in required', 'Sign in to resume live images.', 'login'],
        forbidden: ['access restricted', 'Access to live images is restricted.'],
        invalid: ['invalid response', 'Unexpected response from the image service. Retrying…', 'retry'],
        timeout: ['server timed out', 'Image status request timed out. Retrying…', 'retry'],
        network: ['server offline', 'Connection to the camera server interrupted. Retrying…', 'retry'],
    };

    function ageText(seconds) {
        if (seconds < 60) return seconds + ' s';
        if (seconds < 3600) return Math.floor(seconds / 60) + ' min';
        if (seconds < 86400) return Math.floor(seconds / 3600) + ' h';
        const days = Math.floor(seconds / 86400);
        return days + (days === 1 ? ' day' : ' days');
    }

    function cameraTime(entry) {
        const parts = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/.exec(entry?.captured_at || '');
        if (!parts) return '';
        const offset = parts[3] === 'Z' ? 'UTC' : 'UTC' + parts[3];
        return (entry.time_source === 'file' ? 'File time ' : '') + parts[1] + ' ' + parts[2] + ' ' + offset;
    }

    function follow(view, indicator, endpoint) {
        const canvas = view?.querySelector('canvas');
        let image = null;
        let shown = null;
        let report = {};
        let clock = null;
        let online = null;
        let requestError = null;
        let requestIssue = '';
        let transferError = null;
        let legacyMessage = '';
        let nextDetailsAt = 0;
        const statusText = indicator && byId('status_text');
        const ageLink = indicator && byId('sidebar-image-age');
        const fallback = indicator && byId('sidebar-status-fallback');
        let lastMarkup = null;
        let haveDetails = true; // The template renders the first status report.

        function render() {
            if (!indicator || document.hidden) return;
            const taken = Date.parse(shown?.captured_at);
            const elapsed = clock ? clock.time + performance.now() - clock.syncedAt - taken : NaN;
            const seconds = Number.isFinite(elapsed) ? Math.max(0, Math.floor(elapsed / 1000)) : null;
            const ahead = elapsed < -2000; // Tolerate small differences when timestamps are rounded.
            let age = shown ? 'Image time unknown' : 'Waiting for image';
            if (ahead) age = 'Image time ahead of camera';
            else if (seconds !== null) age = 'Last image ' + ageText(seconds) + ' ago';
            const server = online === true ? 'web server reachable'
                : online === false ? 'web server unreachable' : 'checking web connection';
            const station = !requestError && report.station;
            const stationIssue = station && stationIssues[station.code];
            const late = seconds !== null && seconds >= (report.stale_after_s || 90);
            const delayed = !shown || seconds === null || late || ahead;
            let notice = requestError || transferError;
            if (!notice && stationIssue) notice = ['', ...stationIssue];
            if (!notice && ahead && (!report.reason || delayedReasons.has(report.reason))) {
                notice = ['check clock', 'The displayed image is dated later than the camera clock. Check the camera time and time zone.', 'retry'];
            }
            if (!notice && (delayed || !delayedReasons.has(report.reason))) notice = reasons[report.reason];
            if (!notice && legacyMessage) notice = ['image status', legacyMessage, 'retry'];
            if (!notice && frames?.active && performance.now() - frames.active.startedAt > 800) {
                notice = ['loading image', 'New frame available · loading image…'];
            }
            if (!notice && late) notice = ['waiting for image', 'Waiting for a newer image. Checking automatically.', 'retry'];
            const [summary, note, action] = notice || ['', '', null];
            const detail = stationIssue && transferError && !requestError
                ? stationIssue[0] + ' ' + note : note;
            const adminAction = action === 'settings' || action === 'services';

            // Place the *same* age link alongside the value(s) of {status} in
            // the configured template. Some templates omit that placeholder.
            const markers = !station || !haveDetails ? [] : statusText.querySelectorAll('[data-station-state]');
            const label = station?.label || requestLabels[requestIssue] ||
                (online === null ? 'CHECKING' : 'STATUS UNAVAILABLE');
            const tone = station?.class_name || 'tw:text-warning';
            statusText.hidden = !station || !haveDetails;
            fallback.hidden = markers.length > 0;
            const stateNodes = markers.length ? markers : [byId('sidebar-station-fallback')];
            for (const node of stateNodes) {
                if (node.textContent !== label) node.textContent = label;
                if (node.className !== tone) node.className = tone;
            }
            if (markers.length) {
                if (markers[0].nextElementSibling !== ageLink) markers[0].after(ageLink);
            } else if (ageLink.parentElement !== fallback) {
                fallback.append(ageLink);
            }
            const text = !requestError && summary ? age + ' · ' + summary : age;
            if (ageLink.textContent !== text) ageLink.textContent = text;
            ageLink.title = [label, age, server, cameraTime(shown), detail].filter(Boolean).join(' · ');
            indicator.dataset.state = online === null ? 'checking' : online === false ? 'offline'
                : !station || detail ? 'warning' : station.code === 'running' ? 'ok' : 'neutral';

            const message = byId('sidebar-live-detail');
            if (message.textContent !== detail) message.textContent = detail;
            byId('live-login').hidden = !(action === 'login' || (adminAction && report.can_sign_in_to_manage === true));
            byId('live-retry').hidden = action !== 'retry';
            const settings = byId('live-settings'), services = byId('live-services');
            if (settings) settings.hidden = !(report.can_manage === true && action === 'settings');
            if (services) services.hidden = !(report.can_manage === true && action === 'services');
        }

        function draw() {
            if (!canvas || !image) return;
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            const scale = Math.min(canvas.width / image.naturalWidth, canvas.height / image.naturalHeight);
            const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
            canvas.getContext('2d').drawImage(image, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
        }

        const frames = view && new LiveFrameLoader((loaded, entry) => {
            image = loaded;
            if (canvas) {
                draw();
            } else {
                const previous = byId('latest-image');
                image.id = previous.id;
                image.className = previous.className;
                image.alt = previous.alt;
                previous.replaceWith(image);
            }
            shown = entry;
            transferError = null;
            render();
        }, issue => {
            transferError = ['image retrying', issue === 'timeout' ? 'Image download timed out. Retrying…' : 'Image could not be loaded. Retrying…', 'retry'];
            render();
        });

        const url = new URL(endpoint, document.baseURI);
        url.searchParams.set('live_status', '1');
        const interval = view ? Math.max(2000, Math.min(5000, Number(view.dataset.interval))) : 15000;
        const poll = new LiveJsonPoll(() => {
            if (indicator && performance.now() >= nextDetailsAt) {
                url.searchParams.set('status_details', '1');
                nextDetailsAt = performance.now() + 60000;
            } else {
                url.searchParams.delete('status_details');
            }
            return url;
        }, interval, payload => {
            const entry = payload?.latest_image;
            if (!entry || typeof entry.message !== 'string' || !(entry.url === null || typeof entry.url === 'string')) {
                throw new Error('Invalid latest image');
            }
            report = payload.live_status || {};
            if (indicator && typeof payload.status_text === 'string') {
                if (payload.status_text !== lastMarkup) {
                    // Custom templates may contain trusted HTML and legacy Bootstrap colors.
                    statusText.innerHTML = payload.status_text.replace(/class="text-success"/g, 'class="tw:text-success"')
                        .replace(/class="text-(danger|error)"/g, 'class="tw:text-error"');
                    lastMarkup = payload.status_text;
                }
                haveDetails = true;
            }
            const time = Date.parse(report.now);
            if (Number.isFinite(time)) clock = {time, syncedAt: performance.now()};
            online = true;
            requestError = null;
            requestIssue = '';
            // Older servers use line breaks and a warning div in their daytime status.
            legacyMessage = report.reason ? '' : entry.message.replace(/<br\s*\/?\s*>|<\/?div\b[^>]*>/gi, ' ').trim();
            if (!frames) {
                shown = entry.url ? entry : null;
            } else if (entry.url) {
                const key = entry.frame_key || entry.url;
                if (key === frames.displayedKey) transferError = null;
                frames.offer(key, entry.url, entry);
            } else {
                frames.stop();
                transferError = null;
            }
            render();
        }, (issue, code) => {
            online = issue !== 'network' && issue !== 'timeout';
            requestError = requestErrors[issue] || ['image service error', 'Image service error (HTTP ' + code + '). Retrying…', 'retry'];
            requestIssue = issue;
            haveDetails = false;
            nextDetailsAt = 0; // Recover the entire status panel after reconnection.
            render();
        });

        if (indicator) {
            byId('live-retry').addEventListener('click', () => {
                frames?.stop();
                poll.refresh();
            });
            window.setInterval(render, 1000);
        }
        if (view) {
            view.addEventListener('click', event => {
                if (!event.target.closest('[data-live-fullscreen], #latest-image, #canvas')) return;
                const screen = view.querySelector('[data-live-screen]');
                if (document.fullscreenElement || document.webkitFullscreenElement) {
                    (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
                } else {
                    (screen.requestFullscreen || screen.webkitRequestFullscreen)?.call(screen);
                }
            });
            window.addEventListener('resize', draw);
        }
        followLivePage([poll], frames);
    }

    const statusUrl = sidebar?.dataset?.endpoint;
    const viewSource = page && new URL(page.dataset.endpoint, document.baseURI);
    const menuSource = statusUrl && new URL(statusUrl, document.baseURI);
    const shared = viewSource && menuSource && viewSource.pathname === menuSource.pathname &&
        viewSource.searchParams.get('camera_id') === menuSource.searchParams.get('camera_id');
    if (page) follow(page, shared ? sidebar : null, page.dataset.endpoint);
    if (statusUrl && !shared) follow(null, sidebar, statusUrl);
})();
