'use strict';

// Each poll owns its request and timer. A late response after sleep or a
// selection change must not overwrite the result of the replacement request.
class LiveJsonPoll {
    constructor(url, interval, receive, failed) {
        this.url = url;
        this.interval = interval;
        this.receive = receive;
        this.failed = failed;
    }

    stop() {
        clearTimeout(this.timer);
        if (this.request) this.request.abort();
        this.request = null;
    }

    async refresh() {
        this.stop();
        if (document.hidden) return;
        const request = new AbortController();
        this.request = request;
        const timeout = setTimeout(() => request.abort(), 16000);
        let delay = this.interval;
        let issue = 'network';
        try {
            const response = await fetch(this.url(), {
                cache: 'no-store', credentials: 'same-origin', signal: request.signal,
                headers: {Accept: 'application/json'},
            });
            if (!response.ok) {
                issue = response.status === 401 ? 'login' : response.status === 403 ? 'forbidden' : 'server';
                throw new Error(String(response.status));
            }
            const contentType = response.headers.get('content-type') || '';
            const atLogin = response.redirected && /\/login\/?$/.test(new URL(response.url).pathname);
            issue = atLogin && contentType.includes('text/html') ? 'login' : 'invalid';
            if (!contentType.includes('application/json')) throw new Error('Expected JSON');
            const payload = await response.json();
            if (this.request === request && !request.signal.aborted) this.receive(payload);
        } catch (error) {
            if (this.request === request) {
                if (request.signal.aborted) issue = 'timeout';
                this.failed(issue, error.message);
                delay = Math.max(5000, Math.min(this.interval, 15000));
            }
        } finally {
            clearTimeout(timeout);
            if (this.request === request) {
                this.request = null;
                if (!document.hidden) this.timer = setTimeout(() => this.refresh(), delay);
            }
        }
    }
}

// Decode one image at a time. During a slow download, keep only the latest
// announcement; display the completed frame before starting the next one.
class LiveFrameLoader {
    constructor(display, failed) {
        this.display = display;
        this.failed = failed;
        this.displayedKey = null;
        this.active = null;
        this.next = null;
    }

    offer(key, url, entry) {
        if (this.active) {
            this.next = this.active.key === key ? null : {key, url, entry};
        } else if (key !== this.displayedKey) {
            this.load({key, url, entry});
        }
    }

    stop() {
        this.next = null;
        if (this.active) {
            clearTimeout(this.active.deadline);
            this.active.image.onload = this.active.image.onerror = null;
            this.active.image.removeAttribute('src');
            this.active = null;
        }
    }

    load(frame) {
        const image = new Image();
        const finish = issue => {
            if (!this.active || this.active.image !== image) return;
            clearTimeout(this.active.deadline);
            image.onload = image.onerror = null;
            this.active = null;
            if (issue) {
                image.removeAttribute('src');
                this.failed(issue);
            } else {
                this.display(image, frame.entry);
                this.displayedKey = frame.key;
            }
            const next = this.next;
            this.next = null;
            if (next && next.key !== this.displayedKey) this.load(next);
        };
        this.active = {key: frame.key, image, startedAt: performance.now(), deadline: setTimeout(() => finish('timeout'), 30000)};
        image.onload = () => finish(null);
        image.onerror = () => finish('image');
        image.src = frame.url;
    }
}

function followLivePage(polls, frames) {
    const pause = () => {
        for (const poll of polls) poll.stop();
        frames.stop();
    };
    const resume = () => {
        pause();
        if (!document.hidden) for (const poll of polls) poll.refresh();
    };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('offline', resume);
    window.addEventListener('online', resume);
    window.addEventListener('pagehide', pause);
    window.addEventListener('pageshow', event => { if (event.persisted) resume(); });
    resume();
}
