'use strict';

(() => {
    const page = document.getElementById('live-view');
    const canvas = page.querySelector('canvas');
    const overlay = document.getElementById('status-overlay');
    const message = document.getElementById('message');
    let frame = null;
    let serverStatus = '';
    let transferStatus = '';
    let connectionStatus = '';

    function status() {
        const text = connectionStatus || transferStatus || serverStatus;
        message.textContent = text;
        overlay.classList.toggle('tw:hidden', !text);
    }

    function draw() {
        if (!canvas || !frame) return;
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const scale = Math.min(canvas.width / frame.naturalWidth, canvas.height / frame.naturalHeight);
        const width = frame.naturalWidth * scale;
        const height = frame.naturalHeight * scale;
        canvas.getContext('2d').drawImage(frame, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height);
    }

    const frames = new LiveFrameLoader(image => {
        frame = image;
        if (canvas) {
            draw();
        } else {
            const previous = document.getElementById('latest-image');
            image.id = previous.id;
            image.className = previous.className;
            image.alt = previous.alt;
            previous.replaceWith(image);
        }
        transferStatus = '';
        status();
    }, issue => {
        transferStatus = issue === 'timeout' ? 'Image download timed out. Retrying…' : 'Image could not be loaded. Retrying…';
        status();
    });

    const url = new URL(page.dataset.endpoint, document.baseURI);
    const poll = new LiveJsonPoll(() => url, Math.max(2000, Math.min(5000, Number(page.dataset.interval))),
        payload => {
            const entry = payload?.latest_image;
            if (!entry || typeof entry.message !== 'string' || !(entry.url === null || typeof entry.url === 'string')) {
                throw new Error('Invalid latest image');
            }
            connectionStatus = '';
            // The API uses line breaks and a warning div in its daytime status.
            serverStatus = entry.message.replace(/<br\s*\/?\s*>|<\/?div\b[^>]*>/gi, ' ').trim();
            if (entry.url) {
                if (entry.url !== frames.displayedKey && !transferStatus) transferStatus = 'New frame available · loading image…';
                if (entry.url === frames.displayedKey) transferStatus = '';
                frames.offer(entry.url, entry.url, entry);
            } else {
                frames.stop();
                transferStatus = '';
            }
            status();
        }, (issue, code) => {
            const messages = {login: 'Sign in to resume live images.', forbidden: 'Access to live images is restricted.',
                invalid: 'Unexpected response from the image service.', timeout: 'Image status request timed out. Retrying…',
                network: 'Connection to the camera server interrupted. Retrying…', server: 'Image service error (HTTP ' + code + '). Retrying…'};
            connectionStatus = messages[issue];
            status();
        });

    function fullscreen() {
        const element = canvas || page.querySelector('[data-live-screen]');
        if (document.fullscreenElement || document.webkitFullscreenElement) {
            (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
        } else {
            (element.requestFullscreen || element.webkitRequestFullscreen)?.call(element);
        }
    }
    page.addEventListener('click', event => {
        if (event.target.closest('[data-live-fullscreen], #latest-image, #canvas')) fullscreen();
    });
    window.addEventListener('resize', draw);
    followLivePage([poll], frames);
})();
