/* The live Focus page: the idle view, and a focus session over /ws/focus.
 *
 * Sections: pure helpers (no DOM; tests/focus/test_focus_page_js.py runs them with node), then, in the browser only:
 * page state, connection and clock, frames, status line, the number, rings and stars, camera and region controls,
 * loading signs, the lens, graph and autofocus (capture moves the lens; this page only sends commands), the session's
 * steps, the hand-turned rig's trace, idle warning, the idle view, and start-up.
 *
 * Message data is never put into the page as HTML: text goes in with textContent, rings are built with
 * createElementNS.
 */
(function () {
    'use strict';

    // ==== pure helpers ===========================================================================================

    var HEADER_SIZE = 29;          // struct '>4sBIdffI' (indi_allsky/focus/frame.py HEADER)
    var HEADER_VERSION = 1;
    var CMD_ID_MAX = 4294967295;   // 2**32 - 1
    var STALL_INTERVALS = 3;       // Stalled after this many expected intervals with no picture
    var STALL_MIN_S = 1.0;         // ... and never sooner than this, so a network hiccup does not flash red
    var RING_PICK_PX = 12;         // a tap picks the nearest ring within this many screen px

    var ENDED_TEXT = {
        'done': 'The focus session ended: the focus was saved.',
        'cancelled': 'The focus session ended: Cancel was pressed, and the lens is back where it was at Start.',
        'cancelled_hand': 'The focus session ended: Cancel was pressed.',
        'cancel_short': 'The focus session ended: Cancel was pressed, but the lens could not get back to where it ' +
            'was at Start. The indi-allsky log says where it stopped.',
        'no_page': 'The focus session ended: no focus page was open for 2 minutes.',
        'idle': 'The focus session ended: nobody touched the page for 15 minutes.',
        'failed': 'The focus session ended because something failed. The indi-allsky log says what.',
        'stopped': 'The focus session ended: the capture program stopped or reloaded.',
        'slow': 'This page was closed because it could not keep up with the pictures. It reconnects by itself.'
    };

    // The 29-byte frame header, big-endian, no padding. Null when it is not a frame this page knows.
    function parseHeader(buf) {
        if (!buf || buf.byteLength < HEADER_SIZE) {
            return null;
        }
        var v = new DataView(buf, 0, HEADER_SIZE);
        if (v.getUint8(0) !== 0x49 || v.getUint8(1) !== 0x41 || v.getUint8(2) !== 0x46 || v.getUint8(3) !== 0x46) {
            return null;  // 'IAFF'
        }
        if (v.getUint8(4) !== HEADER_VERSION) {
            return null;
        }
        return {
            frame_no: v.getUint32(5, false),
            capture_time: v.getFloat64(9, false),
            exposure: v.getFloat32(17, false),
            gain: v.getFloat32(21, false),
            cmd_id: v.getUint32(25, false)
        };
    }

    // Server clock minus page clock (s), from the ping with the shortest round trip: [{rtt, offset}].
    function bestOffset(samples) {
        var best = null;
        for (var i = 0; i < samples.length; i++) {
            if (best === null || samples[i].rtt < best.rtt) {
                best = samples[i];
            }
        }
        return best === null ? null : best.offset;
    }

    // One ping sample: sent and received in page seconds, serverT in server seconds.
    function clockSample(sent, received, serverT) {
        return {rtt: received - sent, offset: serverT - (sent + received) / 2};
    }

    // 'live' | 'waiting' | 'stalled'. sinceFrame: s since the last picture arrived (null: none yet);
    // interval: the expected s between pictures; pending: a command of this page is not in the picture yet.
    function statusState(sinceFrame, interval, pending) {
        if (sinceFrame === null) {
            return 'waiting';
        }
        if (sinceFrame > Math.max(STALL_INTERVALS * interval, STALL_MIN_S)) {
            return 'stalled';
        }
        return pending ? 'waiting' : 'live';
    }

    // Why a session ended: a code from capture, or a full sentence from the web program (shown as it is).
    function endedText(reason) {
        if (reason === null || reason === undefined || reason === '') {
            return '';
        }
        return Object.prototype.hasOwnProperty.call(ENDED_TEXT, reason) ? ENDED_TEXT[reason] : String(reason);
    }

    // The id of the ring nearest (x, y) (picture px) within maxPx screen px; scale is screen px per picture px.
    function nearestRing(rings, x, y, scale, maxPx) {
        var best = null;
        var bestD = Infinity;
        for (var i = 0; i < rings.length; i++) {
            var r = rings[i];
            if (typeof r.x !== 'number' || typeof r.y !== 'number') {
                continue;
            }
            var d = Math.sqrt((r.x - x) * (r.x - x) + (r.y - y) * (r.y - y)) * scale;
            if (d <= maxPx && d < bestD) {
                best = r.id;
                bestD = d;
            }
        }
        return best;
    }

    // Command ids must keep rising across reloads and pages: capture marks each picture with the highest id that
    // had taken effect, so an id below one already seen would clear "not in the picture yet" at once.
    function nextCmdId(lastSent, highestSeen) {
        var n = Math.max(lastSent || 0, highestSeen || 0) + 1;
        return n > CMD_ID_MAX ? 1 : n;
    }

    function fmtAge(s) {
        if (s < 0) {
            s = 0;
        }
        return (s < 1 ? s.toFixed(2) : s < 10 ? s.toFixed(1) : Math.round(s).toString()) + ' s old';
    }

    function fmtExposure(s) {
        if (s >= 1) {
            return (Math.round(s * 10) / 10) + ' s';
        }
        var ms = s * 1000;
        return (ms >= 1 ? Math.round(ms) : Number(ms.toPrecision(2))) + ' ms';
    }

    function fmtGain(g) {
        if (Math.abs(g - Math.round(g)) < 1e-6) {
            return String(Math.round(g));
        }
        return Math.abs(g) < 10 ? String(Number(g.toFixed(2))) : g.toFixed(1);
    }

    // The status line's words when the picture is live. interval: the measured s between pictures
    // (null before two have arrived; the exposure stands in then).
    function liveText(picture, exposure, interval) {
        var valid = typeof exposure === 'number' && exposure > 0;
        if (picture === 'stills') {
            return valid ? 'Still pictures · ' + fmtExposure(exposure) + ' each' : 'Still pictures';
        }
        var every = typeof interval === 'number' && interval > 0 ? Math.max(interval, valid ? exposure : 0) :
            (valid ? exposure : null);
        if (every === null) {
            return 'Live video';
        }
        var rate = 1 / every;
        var n = rate >= 1 ? Math.round(rate) : Number(rate.toFixed(1));
        return 'Live video · ' + n + ' fps';  // frames per second
    }

    // -- commands this page is waiting on: [{id, kind, btn?}]. Each returns a new list.
    // Picture kinds ('motor' | 'camera' | 'region') wait for a picture that shows them: the status line says "not in
    // the picture yet" and the number dims. The others ('autofocus', 'stop', 'graph', 'pick', 'tune') only wait for
    // capture to answer. An entry with `btn` shows a spinner on that button until capture answers (`answered`).
    // A command that takes no id (stop, clear_graph, pick_stars, tune) has id null.

    var PICTURE_KINDS = {motor: true, camera: true, region: true};

    // The Start button: busy from the click until capture answers, which can take seconds while it sets the camera up.
    // The bottom row. saved: the autofocus Save shows above, so this row's Save hides; busy: the lens moves or an
    // autofocus runs; cancelling: Cancel was sent and the lens is on its way back.
    function exitButtons(controls, saved, busy, cancelling) {
        return {
            save: {hidden: saved, disabled: !controls || busy || cancelling},
            cancel: {disabled: !controls || cancelling, busy: cancelling, label: cancelling ? 'Cancelling\u2026' : 'Cancel'}
        };
    }

    // An exposure tune or search holds the lens still: a move mid-tune spoils the exposures it compares (capture
    // refuses one too). `o`: {tuning, searching}.
    function tuneHoldsLens(o) {
        return !!(o.tuning || o.searching);
    }

    // A tune, search or pick is under way: Save waits for it (nothing measured yet says the focus is good).
    // `o`: {tuning, searching, picking}.
    function stepRunning(o) {
        return !!(o.tuning || o.searching || o.picking);
    }

    // The step bar's fill (0-100) for a tune or pick progress message; null hides the bar. The tune's point N is
    // being taken, so N - 1 are done; a pick frame's message arrives once that frame is in.
    function stepBar(msg) {
        if (!msg || msg.done === true || !(msg.of > 0)) {
            return null;
        }
        var done;
        if (msg.what === 'tune' && msg.step > 0) {
            done = msg.step - 1;
        } else if (msg.what === 'pick' && msg.frame > 0) {
            done = msg.frame;
        } else {
            return null;
        }
        return Math.round(Math.min(1, done / msg.of) * 100);
    }

    // One of the idle page's start buttons. `starting`: a start was sent; `mine`: by this button.
    function startButton(open, starting, mine, label) {
        return {disabled: !open || starting, busy: starting && mine, label: starting && mine ? 'Starting\u2026' : label};
    }

    // The Step size list's words: the size in lens degrees ("Fine \u00b7 0.8\u00b0"). `steps` and `perLensTurn` come
    // from a `lens` message; without them the fixed sizes capture starts from (controller.py) stand in.
    var STEP_NAMES = {fine: 'Fine', medium: 'Medium', coarse: 'Coarse'};
    var STEP_DEGREES = {fine: 0.8, medium: 3.5, coarse: 13};

    function stepLabel(name, steps, perLensTurn) {
        var deg = known(steps) && known(perLensTurn) && perLensTurn > 0 ? steps * 360 / perLensTurn : STEP_DEGREES[name];
        var txt = deg < 10 ? deg.toFixed(1) : String(Math.round(deg));
        return STEP_NAMES[name] + ' \u00b7 ' + txt + '\u00b0';
    }

    // The page's questions. `lens`: this rig moves the lens, so ending the session puts it back.
    // n: the safe answer (first, focused, and what Esc or a tap outside means); y: the other.
    var TAKEOVER = 'Live Focus takes over the camera for a while, so sky pictures pause. When the session ends, the ' +
        'camera goes back to how it is now.';
    var TAKEOVER_LENS = ' Cancel also brings the lens back to where it is now.';

    function confirmText(kind, lens) {
        var takeover = TAKEOVER + (lens ? TAKEOVER_LENS : '');
        if (kind === 'start') {
            return {t: 'Take over the camera?', b: takeover, n: 'Not now', y: 'Start Live Preview', danger: false};
        }
        if (kind === 'start_af') {
            return {t: 'Take over the camera?', b: takeover + ' Autofocus starts right away.', n: 'Not now',
                    y: 'Autofocus', danger: false};
        }
        if (kind === 'again') {
            return {t: 'Autofocus again?', b: 'The lens leaves best focus and the scan starts over.', n: 'Keep focus',
                    y: 'Autofocus', danger: false};
        }
        return {t: 'End without saving?',
                b: lens ? 'The lens goes back to where it was at the start, and sky pictures resume.' : 'Sky pictures resume.',
                n: 'Keep going', y: 'End session', danger: true};
    }

    function pendingAdd(list, id, kind, btn) {
        var p = {id: id, kind: kind};
        if (btn) {
            p.btn = btn;
        }
        return list.concat([p]);
    }

    // A picture marked cmdId shows every command up to and including it.
    function pendingShown(list, cmdId) {
        return list.filter(function (p) { return typeof p.id !== 'number' || p.id > cmdId; });
    }

    function pendingDrop(list, id) {
        return list.filter(function (p) { return p.id !== id; });
    }

    function pendingDropKind(list, kind) {
        return list.filter(function (p) { return p.kind !== kind; });
    }

    // The newest entry the status line and the number wait on, or null.
    function pendingPicture(list) {
        for (var i = list.length - 1; i >= 0; i--) {
            if (PICTURE_KINDS[list[i].kind]) {
                return list[i];
            }
        }
        return null;
    }

    // Whether a button still waits for capture's answer.
    function pendingSpins(list, btn) {
        return list.some(function (p) { return p.btn === btn && !p.answered; });
    }

    // Capture answered the command with this id: its button stops spinning (a picture kind still waits for its
    // picture).
    function pendingAnswered(list, id) {
        return list.map(function (p) {
            return p.id === id && typeof id === 'number' ? Object.assign({}, p, {answered: true}) : p;
        }).filter(function (p) { return !(p.answered && !PICTURE_KINDS[p.kind]); });
    }

    // An error refusing a command: drop that command by its id; with no id, the newest of the command's kind.
    var COMMAND_KIND = {set_camera: 'camera', set_region: 'region', move_to: 'motor', nudge: 'motor', back: 'motor',
                        autofocus: 'autofocus', stop: 'stop', clear_graph: 'graph', pick_stars: 'pick', tune: 'tune'};
    function pendingRefused(list, command, cmdId) {
        if (typeof cmdId === 'number') {
            return pendingDrop(list, cmdId);
        }
        var kind = COMMAND_KIND[command];
        for (var i = list.length - 1; kind && i >= 0; i--) {
            if (list[i].kind === kind) {
                return list.slice(0, i).concat(list.slice(i + 1));
            }
        }
        return list;
    }

    // -- the camera controls ----------------------------------------------------------------------------------------

    function known(v) {
        return typeof v === 'number' && isFinite(v);
    }

    // The exposure choices: the ladder inside the camera's limits, plus the current exposure.
    function exposureChoices(ladder, current, min, max) {
        var out = ladder.filter(function (x) {
            return (!known(min) || x >= min) && (!known(max) || x <= max) && Math.abs(x - current) > 1e-9;
        });
        if (known(min) && (!out.length || out[0] > min) && Math.abs(min - current) > 1e-9) {
            out.push(min);
        }
        if (known(max) && Math.abs(max - current) > 1e-9 && out.indexOf(max) < 0) {
            out.push(max);
        }
        out.push(current);
        return out.sort(function (a, b) { return a - b; });
    }

    // The gain slider: the camera's range when known (else 0 .. 600, or twice the current gain), with a fine step
    // when the range is small.
    function gainRange(min, max, current) {
        if (known(min) && known(max) && min === max) {
            // a fixed-gain camera: nothing to choose (capture sends null limits for a camera with no gain control,
            // and the slider then falls back to the defaults below)
            return {min: min, max: max, step: 1, fixed: true};
        }
        // a camera limit is a hard edge (set_camera refuses beyond it); only an unknown end stretches to take in
        // the current gain
        var lo = known(min) ? min : Math.min(0, current);
        var hi = known(max) && max > lo ? max : Math.max(600, Math.ceil(current * 2), lo + 1, current);
        var span = hi - lo;
        return {min: lo, max: hi, step: span < 50 ? span / 100 : 1};
    }

    // The gain to put on the slider and send: inside the span, so a configured gain the camera cannot take is never
    // sent back untouched; a fixed gain is the camera's one value.
    function clampGain(span, g) {
        if (span.fixed) {
            return span.min;
        }
        return Math.min(span.max, Math.max(span.min, g));
    }

    // How long to expect between pictures. Before two have arrived there is no measured gap, and a still picture
    // also takes its download: allow for that so the first picture is not called Stalled.
    var DOWNLOAD_ALLOWANCE_S = 2.0;
    function expectedGap(exposure, gaps) {
        var exp = known(exposure) && exposure > 0 ? exposure : 0.1;
        if (!gaps.length) {
            return exp + DOWNLOAD_ALLOWANCE_S;
        }
        var sorted = gaps.slice().sort(function (a, b) { return a - b; });
        return Math.max(exp, sorted[Math.floor(sorted.length / 2)]);
    }

    // The box on the whole-sensor picture: the current region, or (whole-frame pictures) capture's first-region
    // size centred: capture_session.default_region, a square of at most VIDEO_REGION_PX on the Bayer grid.
    var REGION_PX = 1024;
    function regionBox(W, H, roi) {
        if (Array.isArray(roi) && roi.length === 4) {
            var w = Math.min(W, roi[2]);
            var h = Math.min(H, roi[3]);
            return {x: Math.min(roi[0], W - w), y: Math.min(roi[1], H - h), w: w, h: h};
        }
        var size = Math.min(REGION_PX, W, H);
        size -= size % 2;
        var x = Math.floor((W - size) / 2);
        var y = Math.floor((H - size) / 2);
        return {x: x - x % 2, y: y - y % 2, w: size, h: size};
    }

    // Move region is offered in both modes: a stills rig starts with no region (whole frame) and can
    // still choose one.
    function canMoveRegion(mode) {
        return !!mode && (mode.picture === 'video' || mode.picture === 'stills');
    }

    var STAR_WORDS = {
        kept: 'measured', weak: 'too faint', dropped: 'left out', pinned: 'the only one measured',
        saturated: 'too bright'
    };
    function starWord(state) {
        return Object.prototype.hasOwnProperty.call(STAR_WORDS, state) ? STAR_WORDS[state] : String(state);
    }

    // Stretch sliders: positions 0..SLIDER_MAX on a log-like scale over the share of full scale, so the dark end,
    // where the sky sits (about 1-5 % of full scale), gets most of the travel. 0 -> 0, SLIDER_MAX -> 1.
    var SLIDER_MAX = 1000;
    var LEVEL_DECADES = 4;
    function levelFromSlider(pos) {
        var p = Math.min(1, Math.max(0, Number(pos) / SLIDER_MAX));
        return (Math.pow(10, LEVEL_DECADES * p) - 1) / (Math.pow(10, LEVEL_DECADES) - 1);
    }
    function sliderFromLevel(level) {
        var v = Math.min(1, Math.max(0, Number(level)));
        return Math.round(SLIDER_MAX * Math.log(1 + v * (Math.pow(10, LEVEL_DECADES) - 1)) /
                          Math.log(Math.pow(10, LEVEL_DECADES)));
    }
    // Black stays under white: the slider that did not move gives way, one step past the one that did.
    function orderSliders(black, white, moved) {
        var b = Math.min(SLIDER_MAX, Math.max(0, Math.round(black)));
        var w = Math.min(SLIDER_MAX, Math.max(0, Math.round(white)));
        if (b < w) {
            return [b, w];
        }
        if (moved === 'black') {
            b = Math.min(b, SLIDER_MAX - 1);
            return [b, b + 1];
        }
        w = Math.max(w, 1);
        return [w - 1, w];
    }
    function fmtLevel(level) {
        if (!known(level)) {
            return '–';
        }
        var pct = level * 100;
        if (pct < 1) {
            return pct.toFixed(2) + ' %';
        }
        return (pct < 10 ? pct.toFixed(1) : pct.toFixed(0)) + ' %';
    }
    var STRETCH_NAMES = {auto: 'Auto', manual: 'Manual', off: 'Off'};

    // -- the lens, the graph and autofocus -------------------------

    // Steps from the session start, signed: '+62', '-40', '0'.
    function signed(n) {
        var r = Math.round(n);
        return r > 0 ? '+' + r : String(r);
    }

    // The fitted curve at x: min(P, sqrt(a^2 + (k (x - c))^2)).
    function fitModel(fit, x) {
        var d = fit.k * (x - fit.c);
        return Math.min(fit.P, Math.sqrt(fit.a * fit.a + d * d));
    }

    // A fit with numbers to draw (a fit capture marked not ok still has its curve), else null.
    function drawableFit(fit) {
        if (!fit || typeof fit !== 'object') {
            return null;
        }
        return known(fit.c) && known(fit.a) && known(fit.k) && known(fit.P) ? fit : null;
    }

    // `state.motor`: {configured, ok, reason}. An older capture sent a bare bool (configured, and so ok).
    function motorInfo(m) {
        if (m && typeof m === 'object') {
            return {configured: m.configured === true, ok: m.ok === true,
                    reason: typeof m.reason === 'string' && m.reason ? m.reason : null};
        }
        return {configured: m === true, ok: m === true, reason: null};
    }

    var FRAME_SPAN_STEPS = 8;   // indi_allsky/focus/autofocus.py: one frame smears over at most this many steps

    // Autofocus's time, worked out as capture does (c_guess = here), from a `lens` message and
    // the exposure. Whole seconds, or null without the numbers.
    function autofocusEstimate(lens, exposure) {
        if (!lens || !known(lens.position) || !known(lens.limit) || !known(lens.speed) || lens.speed <= 0 ||
                !known(exposure) || exposure <= 0) {
            return null;
        }
        var here = lens.position;
        var reach = Array.isArray(lens.reachable) && lens.reachable.length === 2 ? lens.reachable :
            [-lens.limit + (lens.backlash || 0), lens.limit];
        var window_ = Math.round(lens.limit / 2);
        var start = Math.max(reach[0], here - window_);
        var end = Math.min(reach[1], here + window_);
        var rate = Math.min(lens.speed, FRAME_SPAN_STEPS / exposure);
        var s = (Math.abs(here - start) + (lens.backlash || 0)) / lens.speed + (end - start) / rate + 3 +
            Math.abs(end - here) / lens.speed;
        return Math.ceil(s);
    }

    // again: a run already succeeded, and another one moves the lens off that result
    function autofocusLabel(seconds, again) {
        var word = again ? 'Autofocus again' : 'Autofocus';
        return known(seconds) && seconds > 0 ? word + ' · about ' + Math.round(seconds) + ' s' : word;
    }

    // A graph target: inside what the lens can reach, snapped to best focus when within snapPx of it, whole steps.
    function graphTarget(x, reach, fit, pxPerStep, snapPx) {
        if (fit && fit.ok && known(fit.c) && Math.abs(x - fit.c) * pxPerStep <= snapPx) {
            x = fit.c;
        }
        if (Array.isArray(reach) && reach.length === 2) {
            x = Math.min(reach[1], Math.max(reach[0], x));
        }
        return Math.round(x);
    }

    // The y axis top: y starts at 0; the top takes in the points (98th percentile, so one wild
    // reading does not squash the rest), the plateau, and never less than `floor`.
    function graphTop(values, fit, floor) {
        var top = floor;
        if (values.length) {
            var sorted = values.slice().sort(function (a, b) { return a - b; });
            top = Math.max(top, sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.98))] * 1.15);
        }
        if (fit && known(fit.P) && fit.P < 1e3) {
            top = Math.max(top, fit.P * 1.1);
        }
        return top;
    }

    // A point's colour by age: green when new, dark purple from FADE_S on.
    var FADE_S = 2;
    var FADE_FROM = [74, 222, 128];   // #4ade80
    var FADE_TO = [109, 40, 217];     // #6d28d9
    function fadeColor(age) {
        var t = Math.min(1, Math.max(0, age / FADE_S));
        var c = FADE_FROM.map(function (v, i) { return Math.round(v + (FADE_TO[i] - v) * t); });
        return 'rgb(' + c.join(',') + ')';
    }

    // The session's steps across the top (Gitea issue 4). With a motor: Tune, Pick stars, Autofocus, Check; without:
    // Tune, Pick stars, Focus by hand. Check is current after an autofocus that finished, or once the lens moved
    // after a pick; it never completes (leaving is Save or Cancel). A preview is Tune, then Preview, until stars
    // are picked (Autofocus picks them first).
    function sessionSteps(o) {
        var keys = o.motor ? ['tune', 'pick', 'autofocus', 'check'] : ['tune', 'pick', 'hand'];
        var current;
        if (o.preview && !o.stars && !o.picking) {
            var look = o.motor ? 'preview' : 'preview-hand';
            keys = ['tune', look];
            current = o.tuning ? 'tune' : look;
        } else if (!o.stars) {
            current = o.tuning && !o.picking ? 'tune' : 'pick';
        } else if (!o.motor) {
            current = 'hand';
        } else if (o.afRunning) {
            current = 'autofocus';
        } else {
            current = o.checking ? 'check' : 'autofocus';
        }
        var at = keys.indexOf(current);
        return keys.map(function (k, i) {
            var state = i < at ? 'done' : i === at ? 'current' : 'todo';
            if (k === 'autofocus' && state === 'done' && !o.afDone) {
                state = 'skipped';  // moved by hand after the pick: Autofocus was never run
            }
            return {key: k, label: STEP_LABELS[k], state: state};
        });
    }
    var STEP_LABELS = {tune: 'Tune exposure', pick: 'Pick stars', autofocus: 'Autofocus', check: 'Check focus',
                       hand: 'Focus by hand', preview: 'Preview', 'preview-hand': 'Preview'};

    // One line under the step bar for the current step only. `busy`: the step is running on its own (a tune, a
    // pick, an autofocus run); otherwise it waits for the reader's button.
    var STEP_HELP = {
        tune: 'Wait while the camera finds the exposure that shows the most stars, as fast as possible.',
        pick: {busy: 'Wait while the stars to measure are chosen. Their size shows how sharp the focus is.',
               idle: 'The stars to measure are picked after the tune, or when Autofocus starts. Their size shows ' +
                   'how sharp the focus is.'},
        autofocus: {busy: 'Wait while the lens moves through focus and settles at the sharpest point.',
                    idle: 'Press Autofocus to move the lens through focus and settle at the sharpest point.'},
        check: 'Check that the stars look sharp. Step the lens in or out, or run Autofocus again, if not.',
        hand: 'Turn the focus ring slowly and watch the star size fall to its lowest.',
        preview: 'Step the lens in or out and watch the picture until the stars look sharp. Press Autofocus ' +
            'to let the camera do it.',
        'preview-hand': 'Turn the focus ring and watch the picture until the stars look sharp.'
    };
    function stepHelp(key, busy) {
        var help = STEP_HELP[key];
        if (help === undefined) {
            return '';
        }
        return typeof help === 'string' ? help : help[busy ? 'busy' : 'idle'];
    }

    var STAGES = ['start', 'scan', 'fit', 'park'];
    var STAGE_WORDS = {start: 'Moving to the start', scan: 'Scanning outward', fit: 'Finding best focus',
                       park: 'Moving to best focus'};
    function stageWords(stage) {
        return Object.prototype.hasOwnProperty.call(STAGE_WORDS, stage) ? STAGE_WORDS[stage] : String(stage);
    }

    // Autofocus's own rows while it runs: [{key, words, state}], the scan row with its frame count.
    function autofocusRows(stages, stage, columns) {
        var list = Array.isArray(stages) && stages.length ? stages : STAGES;
        var at = list.indexOf(stage);
        return list.map(function (k, i) {
            var words = stageWords(k);
            if (k === 'scan' && known(columns) && i <= at) {
                words += '  (' + columns + (columns === 1 ? ' frame)' : ' frames)');
            }
            return {key: k, words: words, state: at < 0 ? 'todo' : i < at ? 'done' : i === at ? 'current' : 'todo'};
        });
    }

    // Seconds left from an estimate taken at t0. A newer estimate never makes the time left jump up.
    function secondsLeft(t0, estimate, now) {
        if (!known(t0) || !known(estimate)) {
            return null;
        }
        return Math.max(0, estimate - (now - t0));
    }

    var pure = {
        signed: signed, fitModel: fitModel, drawableFit: drawableFit, motorInfo: motorInfo,
        autofocusEstimate: autofocusEstimate, autofocusLabel: autofocusLabel, graphTarget: graphTarget,
        graphTop: graphTop, fadeColor: fadeColor, sessionSteps: sessionSteps, stepHelp: stepHelp, stepBar: stepBar, tuneHoldsLens: tuneHoldsLens, stepRunning: stepRunning, startButton: startButton, autofocusRows: autofocusRows,
        stepLabel: stepLabel, confirmText: confirmText,
        secondsLeft: secondsLeft, stageWords: stageWords,
        pendingDropKind: pendingDropKind, pendingPicture: pendingPicture, pendingSpins: pendingSpins,
        pendingAnswered: pendingAnswered,
        levelFromSlider: levelFromSlider, sliderFromLevel: sliderFromLevel, orderSliders: orderSliders,
        fmtLevel: fmtLevel,
        HEADER_SIZE: HEADER_SIZE, parseHeader: parseHeader, bestOffset: bestOffset, clockSample: clockSample,
        statusState: statusState, endedText: endedText, exitButtons: exitButtons, nearestRing: nearestRing, nextCmdId: nextCmdId,
        fmtAge: fmtAge, fmtExposure: fmtExposure, fmtGain: fmtGain, liveText: liveText,
        pendingAdd: pendingAdd, pendingShown: pendingShown, pendingDrop: pendingDrop, pendingRefused: pendingRefused,
        exposureChoices: exposureChoices, gainRange: gainRange, clampGain: clampGain, expectedGap: expectedGap,
        regionBox: regionBox,
        starWord: starWord, canMoveRegion: canMoveRegion
    };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = pure;
    }
    if (typeof document === 'undefined') {
        return;
    }

    // ==== page state =============================================================================================

    var EXPOSURES = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75,
                     1, 2, 3, 5, 10, 15, 20, 30, 60];
    var PING_EVERY_MS = 10000;
    var PINGS_PER_BURST = 8;
    var KEEP_GOING_EVERY_MS = 30000;
    var TRACE_S = 60;

    var MSG_WAITING = {
        'motor': 'Lens moving · not in the picture yet',
        'camera': 'New exposure and gain · not in the picture yet',
        'region': 'Region moving · not in the picture yet'
    };
    var SPIN_TIMEOUT_MS = 15000;    // a button never spins longer than this, whatever capture does
    var MOTOR_SHOWN_MS = 3000;      // after the lens rests, "not in the picture yet" gives up after at least this
    var SNAP_PX = 6;                // a graph release this near best focus snaps to it
    var GRAPH_POINTS_MAX = 20000;   // the page's cap on graph points, like capture's
    var MSG_BACKLASH = 'taking up the backlash';
    var MSG_NEEDS_STARS = 'Autofocus needs stars';
    var MSG_FIRST = 'Waiting for the first picture';
    var MSG_STALLED = 'No new picture · check the camera';
    var MSG_NOT_CONNECTED = 'Not connected to the capture program yet. Try again in a moment.';
    var MSG_WARN = 'Nobody has touched this page for a while. Normal pictures resume in {0} s.';
    var MSG_WARN_WATCHER = 'Nobody is using the focus controls. The focus session ends in {0} s unless an admin ' +
        'keeps it going.';
    var ST = {kept: '#4ade80', weak: '#9ca3af', saturated: '#fbbf24', dropped: '#f87171', pinned: '#60a5fa'};

    var root = document.getElementById('focus-session');
    var $id = function (id) { return document.getElementById(id); };
    var phone = window.matchMedia('(max-width: 767px)');

    var MSG_PLAY_HINT = 'Press Play to move the lens and watch the stars.';
    var PLAN_PREVIEW = 'preview';
    var PLAN_AUTOFOCUS = 'autofocus';
    var ADVANCED_KEY = 'indi-allsky.focus.advanced';

    var S = {
        ws: null, retry: 0, retryTimer: null, rejoined: false,
        session: 'idle', controls: false, rig: null,
        mode: null, reading: null, stars: [], minSnr: 8, snrHeld: null, snrTimer: null, picking: false, tuning: false,
        searching: false,
        starting: false,  // the plan of a start that was sent and capture has not answered yet
        plan: PLAN_AUTOFOCUS,  // capture's word (`state.plan`): a preview stops after the tune
        cancelling: false,  // Cancel was sent and the session has not ended yet
        drawnFrame: -1, captureTime: null, lastArrival: null, intervals: [], highestCmd: 0,
        // ids start from the clock in seconds, so a new page's first command is above every earlier page's ids
        // (capture marks pictures with the highest id that took effect, from any page)
        lastCmd: Math.floor(Date.now() / 1000),
        offset: 0, haveOffset: false, pingSeq: 0, pingsOut: {}, burst: [], pingTimer: null,
        pending: [],                // [{id, kind, btn?}] what this page waits on (see pendingAdd)
        decoding: false, nextFrame: null,
        preview: null,              // {roiKey} while a whole-sensor picture is wanted
        big: false,
        trace: [], best: null, traceMeasure: null,
        warnUntil: null, lastKeep: 0,
        stretch: {mode: 'auto', black: null, white: null},
        stretchHeldUntil: 0,        // ms: this page's slider input wins over incoming levels until then
        stretchSentAt: 0, stretchTimer: null,
        // the first guess, from Config, until capture says (`state.motor`)
        motor: motorInfo({configured: root.getAttribute('data-motor-configured') === '1',
                          ok: root.getAttribute('data-motor-configured') === '1' && !root.getAttribute('data-motor-reason'),
                          reason: root.getAttribute('data-motor-reason')}),
        lens: null,                 // the last `lens` message
        graph: {measure: null, points: [], fit: null},  // points [x, star_id, size, born ms (0: old)]
        drag: null,                 // the step under the pointer while dragging on the graph
        graphRaf: null,
        af: {running: false, stage: null, stages: null, columns: null, t0: null, estimate: null, failed: '',
             done: false},
        lastEstimate: null,         // the last autofocus estimate_s capture sent
        checking: false,            // the Check step is current
        awaitFrame: true            // "Starting live video" until a picture is drawn
    };

    function nowS() {
        return Date.now() / 1000;
    }

    function setText(el, text) {
        if (el && el.textContent !== text) {
            el.textContent = text;
        }
    }

    function show(el, on) {
        if (el) {
            el.hidden = !on;
        }
    }

    var toastTimer = null;
    function toast(text) {
        var el = $id('fs-toast');
        setText(el, text);
        show(el, true);
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { show(el, false); }, 6000);
    }

    // ==== connection and clock ===================================================================================

    function send(msg) {
        if (!S.ws || S.ws.readyState !== WebSocket.OPEN) {
            return false;
        }
        S.ws.send(JSON.stringify(msg));
        return true;
    }

    function connect() {
        S.retryTimer = null;
        var ws;
        try {
            ws = new WebSocket(root.getAttribute('data-ws-url'));
        } catch (e) {
            reconnectLater();
            return;
        }
        ws.binaryType = 'arraybuffer';
        S.ws = ws;
        ws.onopen = function () {
            S.retry = 0;
            S.rejoined = true;  // the next active state starts the live view afresh: it may be another session
            send({kind: 'hello'});
            pingBurst();
            setStartEnabled();
        };
        ws.onmessage = function (e) {
            if (typeof e.data === 'string') {
                var msg;
                try {
                    msg = JSON.parse(e.data);
                } catch (err) {
                    return;
                }
                if (msg && typeof msg === 'object') {
                    onJson(msg);
                }
            } else {
                onFrame(e.data);
            }
        };
        ws.onclose = function () {
            if (S.ws === ws) {
                S.ws = null;
                // what this page was waiting on may never be answered now (a lens move, a preview, a pick's
                // progress); the rejoined page starts clean. The graph stays: reconnecting keeps it.
                S.pending = [];
                S.picking = false;
                S.tuning = false;
                S.searching = false;
                S.starting = false;
                S.af.running = false;  // an autofocus still running says so again with its next progress
                S.awaitFrame = true;
                closeRegion();
                renderStarsUi();
                if (S.session === 'active') {
                    renderNumber();
                    renderPicWait();
                    renderLens();
                }
                setStartEnabled();
                reconnectLater();
            }
        };
    }

    function reconnectLater() {
        if (S.retryTimer === null) {
            var wait = Math.min(30000, 2000 * Math.pow(2, S.retry));
            S.retry += 1;
            S.retryTimer = setTimeout(connect, wait);
        }
    }

    // Every 10 s: 8 pings one after another; the shortest round trip of a finished burst sets the clock offset.
    // Until the first burst finishes, its best sample so far stands in.
    function pingBurst() {
        if (S.burst.length) {
            S.offset = bestOffset(S.burst);
            S.haveOffset = true;
        }
        S.burst = [];
        var stale = nowS() - PING_EVERY_MS / 1000;
        Object.keys(S.pingsOut).forEach(function (id) {
            if (S.pingsOut[id] < stale) {
                delete S.pingsOut[id];  // a pong that never came
            }
        });
        var sent = 0;
        clearTimeout(S.pingTimer);
        (function one() {
            if (sent < PINGS_PER_BURST && send({kind: 'ping', id: ++S.pingSeq})) {
                S.pingsOut[S.pingSeq] = nowS();
                sent += 1;
                S.pingTimer = setTimeout(one, 150);
            } else {
                S.pingTimer = setTimeout(pingBurst, PING_EVERY_MS);
            }
        })();
    }

    function onPong(msg) {
        var sent = S.pingsOut[msg.id];
        if (sent === undefined || typeof msg.t !== 'number') {
            return;
        }
        delete S.pingsOut[msg.id];
        S.burst.push(clockSample(sent, nowS(), msg.t));
        if (!S.haveOffset || S.burst.length >= PINGS_PER_BURST) {
            S.offset = bestOffset(S.burst);
            S.haveOffset = S.haveOffset || S.burst.length >= PINGS_PER_BURST;
        }
    }

    function onJson(msg) {
        switch (msg.kind) {
        case 'state': onState(msg); break;
        case 'pong': onPong(msg); break;
        case 'mode': onMode(msg); break;
        case 'reading': onReading(msg); break;
        case 'measure': onMeasure(msg); break;
        case 'stars': onStars(msg); break;
        case 'stretch': onStretch(msg); break;
        case 'progress': onProgress(msg); break;
        case 'lens': onLens(msg); break;
        case 'graph': onGraph(msg); break;
        case 'fit': onFit(msg); break;
        case 'preview': onPreview(msg); break;
        case 'error': onError(msg); break;
        case 'ended': onEnded(msg); break;
        case 'refused': showEnded(msg.reason); break;
        default: break;
        }
    }

    function onState(msg) {
        startAnswered();
        S.controls = msg.controls === true;
        if (msg.rig && typeof msg.rig === 'object') {
            S.rig = msg.rig;
        }
        if (Object.prototype.hasOwnProperty.call(msg, 'motor')) {
            S.motor = motorInfo(msg.motor);
        }
        if (msg.plan === PLAN_PREVIEW || msg.plan === PLAN_AUTOFOCUS) {
            S.plan = msg.plan;
        }
        if (msg.session === 'active') {
            if (S.session !== 'active' || S.rejoined) {
                enterLive();
            }
            S.rejoined = false;
            S.warnUntil = typeof msg.idle_warning === 'number' ? Date.now() + msg.idle_warning * 1000 : null;
        } else {
            S.rejoined = false;
            if (S.session === 'active') {
                leaveLive();
            }
            if (msg.idle_reason) {
                showEnded(msg.idle_reason);
            }
        }
        renderIdleReason();
        renderControls();
        renderWarn();
        renderLens();
        setStartEnabled();
    }

    function onError(msg) {
        if (msg.command === 'start') {
            startAnswered();
        }
        var text = typeof msg.message === 'string' ? msg.message : '';
        if (text) {
            toast(text);
        }
        // a refused command never takes effect: its sign must not wait for it
        var before = S.pending.length;
        S.pending = pendingRefused(S.pending, msg.command, msg.cmd_id);
        if (S.pending.length !== before && S.session === 'active') {
            renderNumber();
        }
        if (msg.command === 'preview') {
            closeRegion();
        }
        if (msg.command === 'cancel') {
            S.cancelling = false;
            renderExit();
        }
        if (msg.command === 'pick_stars') {
            S.picking = false;
            renderStarsUi();
        }
        renderLens();
    }

    function onEnded(msg) {
        if (msg.reason === 'slow') {
            toast(endedText('slow'));  // only this page was closed; the session goes on and the page rejoins
            return;
        }
        S.pending = [];
        S.cancelling = false;
        closeRegion();
        if (S.session === 'active') {
            leaveLive();
        }
        showEnded(msg.reason);
    }

    function showEnded(reason) {
        var el = $id('fs-ended');
        setText(el, endedText(reason));
        show(el, !!el.textContent);
    }

    // ==== frames =================================================================================================

    function onFrame(buf) {
        var h = parseHeader(buf);
        if (!h || S.session !== 'active') {
            return;
        }
        S.highestCmd = Math.max(S.highestCmd, h.cmd_id);
        var t = nowS();
        if (S.lastArrival !== null) {
            S.intervals.push(t - S.lastArrival);
            if (S.intervals.length > 8) {
                S.intervals.shift();
            }
        }
        S.lastArrival = t;
        if (S.decoding) {
            S.nextFrame = [h, buf];  // newest only
            return;
        }
        decode(h, buf);
    }

    function decode(h, buf) {
        S.decoding = true;
        var blob = new Blob([new Uint8Array(buf, HEADER_SIZE)], {type: 'image/jpeg'});
        createImageBitmap(blob).then(function (bmp) {
            if (h.frame_no > S.drawnFrame) {  // a new session (counting from 1 again) resets drawnFrame in enterLive
                var c = $id('fs-canvas');
                if (c.width !== bmp.width || c.height !== bmp.height) {
                    c.width = bmp.width;
                    c.height = bmp.height;
                }
                c.getContext('2d').drawImage(bmp, 0, 0);
                S.drawnFrame = h.frame_no;
                S.captureTime = h.capture_time;
                if (S.awaitFrame) {
                    S.awaitFrame = false;
                    renderPicWait();
                }
                pictureCmd(h.cmd_id);
            }
            if (bmp.close) {
                bmp.close();
            }
        }).catch(function () {
            // a picture that does not decode is skipped; the next one replaces it
        }).then(function () {
            S.decoding = false;
            var next = S.nextFrame;
            S.nextFrame = null;
            if (next) {
                decode(next[0], next[1]);
            }
        });
    }

    // The picture on screen carries the highest command that had taken effect when it was exposed.
    function pictureCmd(cmdId) {
        setPending(pendingShown(S.pending, cmdId));
    }

    // Replace the waiting list, and redraw what shows it when it changed.
    function setPending(list) {
        var changed = list.length !== S.pending.length || list.some(function (p, i) { return p !== S.pending[i]; });
        S.pending = list;
        if (changed && S.session === 'active') {
            renderNumber();
            renderLens();
            renderStarsUi();
        }
    }

    // Send msg and mark what waits for it: kind (see pendingAdd), btn the button that spins until capture answers.
    // withId: the command carries a cmd_id. Returns the id (or true without one), null when
    // the socket is down.
    function command(msg, kind, btn, withId) {
        var id = null;
        if (withId !== false) {
            id = nextCmdId(S.lastCmd, S.highestCmd);
            S.lastCmd = id;
            msg.cmd_id = id;
        }
        if (!send(msg)) {
            toast(MSG_NOT_CONNECTED);
            return null;
        }
        S.pending = pendingAdd(S.pending, id, kind, btn);
        S.pending[S.pending.length - 1].at = Date.now();
        renderNumber();
        renderLens();
        renderStarsUi();
        return id === null ? true : id;
    }

    // Drop what waits too long: a button that capture never answered, a move whose picture never came.
    function expirePending() {
        var now = Date.now();
        var rested = Math.max(MOTOR_SHOWN_MS, 3000 * expectedInterval() + 1000);
        setPending(S.pending.filter(function (p) {
            if (p.restAt) {
                return now - p.restAt < rested;
            }
            if (PICTURE_KINDS[p.kind] && p.kind !== 'motor') {
                return true;  // a new exposure or region waits for its picture, however slow the camera
            }
            return p.answered || now - (p.at || now) < SPIN_TIMEOUT_MS;
        }));
    }

    // ==== status line ============================================================================================

    function medianInterval() {
        if (!S.intervals.length) {
            return null;
        }
        var sorted = S.intervals.slice().sort(function (a, b) { return a - b; });
        return sorted[Math.floor(sorted.length / 2)];
    }

    function expectedInterval() {
        return expectedGap(S.mode ? S.mode.exposure : null, S.intervals);
    }

    function renderStatus() {
        var since = S.lastArrival === null ? null : nowS() - S.lastArrival;
        var waiting = pendingPicture(S.pending);
        var state = statusState(since, expectedInterval(), waiting !== null);
        var text;
        if (state === 'stalled') {
            text = MSG_STALLED;
        } else if (since === null) {
            text = MSG_FIRST;
        } else if (waiting) {
            text = MSG_WAITING[waiting.kind];
        } else {
            text = S.mode ? liveText(S.mode.picture, S.mode.exposure, medianInterval()) : '';
        }
        var live = $id('fs-live');
        if (live.getAttribute('data-status') !== state) {
            live.setAttribute('data-status', state);
        }
        setText($id('fs-age'), S.captureTime === null ? '' : fmtAge(nowS() + S.offset - S.captureTime));
        setText($id('fs-stxt'), text);
    }

    function renderMode() {
        var m = S.mode;
        var reason = m && m.reason ? String(m.reason) : '';
        var text = '';
        if (m && m.picture === 'stills') {
            text = 'Still pictures: ' + reason;
        } else if (reason && reason.indexOf('Live video') !== 0) {
            text = reason;
        }
        setText($id('fs-mode'), text);
        if (m) {
            setText($id('fs-exp-btn'), 'Exposure ' + fmtExposure(m.exposure) + ' ▾');
            setText($id('fs-gain-btn'), 'Gain ' + fmtGain(m.gain) + ' ▾');
        }
        var regionBtn = $id('fs-region-btn');
        if (regionBtn) {
            show(regionBtn, canMoveRegion(m));
        }
    }

    // ==== the number =============================================================================================

    function onReading(msg) {
        if (typeof msg.cmd_id === 'number') {
            S.highestCmd = Math.max(S.highestCmd, msg.cmd_id);
        }
        S.reading = msg;
        traceAdd(msg);
        graphAdd(msg);
        motorShown(msg);
        renderNumber();
        drawRings();
        renderLens();
    }

    function onMeasure(msg) {
        var was = S.traceMeasure;
        if (was && msg.measure !== was && (msg.measure === 'stars' || msg.measure === 'contrast')) {
            var graph = S.motor.ok;  // a motor rig has the graph; a hand-turned one the trace
            var stars = msg.measure === 'stars';
            setText($id('fs-progress'), graph ?
                (stars ? 'Stars found. The graph starts again with star size.' :
                    'No stars found. The graph starts again with the contrast score.') :
                (stars ? 'Stars found. The trace starts again with star size.' :
                    'No stars found. The trace starts again with the contrast score.'));
        }
        traceReset(msg.measure);
    }

    function renderNumber() {
        var r = S.reading;
        var label = '';
        var value = '–';
        var unit = '';
        var sub = '';
        if (r && r.measure === 'stars' && typeof r.size === 'number') {
            value = r.size.toFixed(2);
            unit = ' px';
            var pinned = (r.rings || []).filter(function (g) { return g.state === 'pinned'; })[0];
            sub = pinned ? 'star ' + (pinned.id + 1) + ' only' :
                'average of ' + r.stars_used + (r.stars_used === 1 ? ' star' : ' stars');
        } else if (r && r.measure === 'contrast' && typeof r.contrast === 'number') {
            label = 'Contrast score ';
            value = r.contrast >= 10 ? String(Math.round(r.contrast)) : r.contrast.toFixed(1);
            sub = 'No stars found · higher is sharper';
        } else if (r && r.message) {
            sub = String(r.message);
        }
        var hasValue = value !== '–';
        var waiting = pendingPicture(S.pending);
        var moving = waiting !== null && hasValue;
        var before = '';
        if (moving) {
            before = waiting.kind === 'motor' ? 'from before your move' : 'from before your change';
        } else if (hasValue && r.message) {
            before = String(r.message);
        }
        var v = $id('fs-value');
        setText($id('fs-value-n'), label + value);
        setText($id('fs-value-unit'), unit);
        v.classList.toggle('fs-dim', moving || !hasValue);
        setText($id('fs-sub'), sub);
        $id('fs-sub').classList.toggle('fs-dim', moving);
        setText($id('fs-sub2'), before);
    }

    // ==== rings and stars ========================================================================================

    function starById(id) {
        for (var i = 0; i < S.stars.length; i++) {
            if (S.stars[i].id === id) {
                return S.stars[i];
            }
        }
        return null;
    }

    // The state drawn: while the brightness slider is held, kept and weak follow it here, not the server.
    function shownState(id, state) {
        var s = starById(id);
        if (S.snrHeld !== null && s && (state === 'kept' || state === 'weak') && typeof s.snr1 === 'number') {
            return s.snr1 < S.snrHeld ? 'weak' : 'kept';
        }
        return state;
    }

    function ringList() {
        if (!S.stars.length) {
            return [];
        }
        var r = S.reading;
        if (r && r.rings && r.rings.length) {
            return r.rings;
        }
        return S.stars;
    }

    function pictureSize() {
        var r = S.reading;
        if (r && r.width && r.height) {
            return [r.width, r.height];
        }
        var c = $id('fs-canvas');
        return [c.width * 2, c.height * 2];  // the JPEG is half size
    }

    function svgEl(name, attrs) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', name);
        for (var k in attrs) {
            if (Object.prototype.hasOwnProperty.call(attrs, k)) {
                el.setAttribute(k, attrs[k]);
            }
        }
        return el;
    }

    function drawRings() {
        var svg = $id('fs-rings');
        var wh = pictureSize();
        var vb = '0 0 ' + wh[0] + ' ' + wh[1];
        if (svg.getAttribute('viewBox') !== vb) {
            svg.setAttribute('viewBox', vb);
        }
        while (svg.firstChild) {
            svg.removeChild(svg.firstChild);
        }
        var shown = $id('fs-pic').clientWidth || 1;
        var k = wh[0] / shown;  // picture px per screen px
        var rings = ringList();
        for (var i = 0; i < rings.length; i++) {
            var g = rings[i];
            if (typeof g.x !== 'number' || typeof g.y !== 'number') {
                continue;
            }
            var st = shownState(g.id, g.state);
            var col = ST[st] || ST.kept;
            var rad = (S.big ? 12 : 9) * k;
            var circle = svgEl('circle', {cx: g.x, cy: g.y, r: rad, fill: 'none', stroke: col,
                                          'stroke-width': (st === 'pinned' ? 3 : 2) * k});
            if (st === 'dropped') {
                circle.setAttribute('stroke-dasharray', (5 * k) + ' ' + (4 * k));
            } else if (st === 'weak') {
                circle.setAttribute('stroke-dasharray', (2 * k) + ' ' + (4 * k));
            }
            svg.appendChild(circle);
            var label = svgEl('text', {x: g.x + rad + 2 * k, y: g.y - rad + 4 * k, fill: col,
                                       'font-size': 13 * k, 'font-weight': 700, 'paint-order': 'stroke',
                                       stroke: '#000', 'stroke-width': 3 * k});
            label.textContent = String(g.id + 1);
            svg.appendChild(label);
        }
    }

    function onStars(msg) {
        S.stars = Array.isArray(msg.stars) ? msg.stars : [];
        if (typeof msg.min_snr === 'number') {
            S.minSnr = msg.min_snr;
            if (S.snrHeld !== null && Math.abs(S.snrHeld - msg.min_snr) < 1e-6) {
                S.snrHeld = null;
            }
        }
        if (!S.stars.length && S.reading) {
            S.reading.rings = [];
        }
        traceReset(S.traceMeasure);  // a new star set: sizes before it do not compare
        renderStarsUi();
        drawRings();
    }

    function onProgress(msg) {
        if (msg.what === 'autofocus') {
            onAutofocus(msg);
            return;
        }
        setText($id('fs-progress'), typeof msg.message === 'string' ? msg.message : '');
        if (msg.what === 'pick' || msg.what === 'tune') {
            renderStepBar(msg);
        }
        if (msg.what === 'pick') {
            S.picking = msg.done !== true;
            S.pending = pendingDropKind(S.pending, 'pick');
        } else if (msg.what === 'tune') {
            S.tuning = msg.done !== true;
            S.pending = pendingDropKind(S.pending, 'tune');
        } else if (msg.what === 'exposure_search') {
            S.searching = msg.done !== true;  // a stills rig's search: the Tune step
        }
        renderStarsUi();
        renderLens();
    }

    // keep -> drop -> pin -> keep (tap to drop, tap again to pin)
    function nextStarState(state) {
        if (state === 'dropped') {
            return 'pin';
        }
        return state === 'pinned' ? 'keep' : 'drop';
    }

    function tapStar(id) {
        var s = starById(id);
        if (s && S.controls) {
            send({kind: 'star', id: id, state: nextStarState(s.state)});
        }
    }

    function renderStarsUi() {
        var c = S.controls && S.session === 'active';
        show($id('fs-stars-chip'), c && S.stars.length > 0);
        show($id('fs-next'), c && S.stars.length > 0);
        show($id('fs-next-motor'), S.motor.ok);
        show($id('fs-next-hand'), !S.motor.ok);
        if ($id('fs-repick')) {
            $id('fs-repick').disabled = S.picking || S.tuning;
        }
        if ($id('fs-tune')) {
            spin($id('fs-tune'), pendingSpins(S.pending, 'fs-tune'));
            $id('fs-tune').disabled = S.picking || S.tuning || pendingSpins(S.pending, 'fs-tune');
        }
        renderSteps();
        if (!c || !S.stars.length) {
            show($id('fs-stars-pop'), false);
        }
        var range = $id('fs-snr');
        if (range && S.snrHeld === null) {
            range.value = S.minSnr;
            setText($id('fs-snr-v'), String(Math.round(S.minSnr)));
        }
        var list = $id('fs-stars-list');
        if (!list) {
            return;
        }
        while (list.firstChild) {
            list.removeChild(list.firstChild);
        }
        S.stars.forEach(function (s) {
            var li = document.createElement('li');
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'tw:btn tw:btn-xs tw:btn-ghost';
            var st = shownState(s.id, s.state);
            b.style.color = ST[st] || '';
            b.textContent = 'Star ' + (s.id + 1) + ' · S/N ' + (typeof s.snr1 === 'number' ? s.snr1.toFixed(0) : '?') +
                ' · ' + starWord(st);
            b.addEventListener('click', function () { tapStar(s.id); });
            li.appendChild(b);
            list.appendChild(li);
        });
    }

    function onPictureTap(e) {
        if (phone.matches && !S.big) {
            setBig(true);
            return;
        }
        if (!S.controls || !S.stars.length || !advanced()) {
            return;  // the rings are Advanced: a tap must not pin a star nobody can see
        }
        var rect = $id('fs-canvas').getBoundingClientRect();
        var wh = pictureSize();
        var scale = rect.width / wh[0];
        var x = (e.clientX - rect.left) / scale;
        var y = (e.clientY - rect.top) / scale;
        var id = nearestRing(ringList(), x, y, scale, RING_PICK_PX);
        if (id !== null) {
            tapStar(id);
        }
    }

    function setBig(on) {
        S.big = on;
        $id('fs-live').classList.toggle('fs-big', on);
        show($id('fs-shrink'), on);
        drawRings();
        drawTrace();
    }

    // ==== camera and region controls =============================================================================

    var expChoices = EXPOSURES.slice();
    var gainSpan = {min: 0, max: 600, step: 1};
    var camTouched = {exp: false, gain: false};

    function openCamera() {
        var pop = $id('fs-cam-pop');
        var opening = pop.hidden;
        show(pop, opening);
        $id('fs-exp-btn').setAttribute('aria-expanded', String(opening));
        $id('fs-gain-btn').setAttribute('aria-expanded', String(opening));
        if (!opening || !S.mode) {
            return;
        }
        // the camera's own value is always on the slider, so Apply without touching it sends it back unchanged
        var m = S.mode;
        var exp = m.exposure;
        var gain = m.gain;
        // the camera's limits come in `mode`; a limit capture does not know is null and the defaults stand
        expChoices = exposureChoices(EXPOSURES, exp, m.exposure_min, m.exposure_max);
        var r = $id('fs-exp');
        r.max = expChoices.length - 1;
        r.value = expChoices.indexOf(exp);
        gainSpan = gainRange(m.gain_min, m.gain_max, gain);
        var g = $id('fs-gain');
        g.min = gainSpan.min;
        g.max = gainSpan.max;
        g.step = gainSpan.step;
        g.value = clampGain(gainSpan, gain);
        g.disabled = !!gainSpan.fixed;  // a fixed-gain camera: the value shows, nothing to slide
        g.title = gainSpan.fixed ? 'This camera has a fixed gain.' : '';
        camTouched = {exp: false, gain: false};
        showCamera();
    }

    function chosenGain() {
        if (!camTouched.gain || gainSpan.fixed) {
            return clampGain(gainSpan, S.mode.gain);
        }
        var v = Number($id('fs-gain').value);
        // whole numbers on a wide range; two decimals on a narrow one (step = range / 100)
        v = gainSpan.step >= 1 ? Math.round(v) : Math.round(v * 100) / 100;
        return clampGain(gainSpan, v);
    }

    function showCamera() {
        setText($id('fs-exp-v'), fmtExposure(expChoices[Number($id('fs-exp').value)]));
        setText($id('fs-gain-v'), fmtGain(chosenGain()));
    }

    function applyCamera() {
        if (!S.mode) {
            return;
        }
        var exp = camTouched.exp ? expChoices[Number($id('fs-exp').value)] : S.mode.exposure;
        command({kind: 'set_camera', exposure: exp, gain: chosenGain()}, 'camera');
        show($id('fs-cam-pop'), false);
    }

    // ---- stretch: the picture's levels, shared by every page --------------------------------------------------
    var STRETCH_SEND_MS = 100;  // slider sends: at most this often, and the last position always goes
    var STRETCH_HOLD_MS = 1000; // after this page's own slider input, incoming levels leave the sliders alone

    function onStretch(msg) {
        if (!Object.prototype.hasOwnProperty.call(STRETCH_NAMES, msg.mode)) {
            return;
        }
        S.stretch = {mode: msg.mode, black: known(msg.black) ? msg.black : null,
                     white: known(msg.white) ? msg.white : null};
        renderStretch(Date.now() >= S.stretchHeldUntil);
    }

    function renderStretch(moveSliders) {
        var st = S.stretch;
        var btn = $id('fs-stretch-btn');
        if (!btn) {
            return;  // a watcher's page has no stretch controls
        }
        setText(btn, 'Stretch ' + STRETCH_NAMES[st.mode] + ' ▾');
        ['auto', 'manual', 'off'].forEach(function (m) {
            $id('fs-stretch-' + m).setAttribute('aria-pressed', String(st.mode === m));
            $id('fs-stretch-' + m).classList.toggle('tw:btn-active', st.mode === m);
        });
        show($id('fs-stretch-auto-row'), st.mode === 'auto');
        show($id('fs-stretch-manual-row'), st.mode === 'manual');
        setText($id('fs-stretch-auto-v'), st.black === null ? 'Levelling…' :
                'Black ' + fmtLevel(st.black) + ' · White ' + fmtLevel(st.white));
        if (moveSliders && st.mode === 'manual' && st.black !== null) {
            $id('fs-black').value = sliderFromLevel(st.black);
            $id('fs-white').value = sliderFromLevel(st.white);
        }
        showLevels();
    }

    function showLevels() {
        setText($id('fs-black-v'), fmtLevel(levelFromSlider($id('fs-black').value)));
        setText($id('fs-white-v'), fmtLevel(levelFromSlider($id('fs-white').value)));
    }

    function openStretch() {
        var pop = $id('fs-stretch-pop');
        show(pop, pop.hidden);
        $id('fs-stretch-btn').setAttribute('aria-expanded', String(!pop.hidden));
        renderStretch(true);
    }

    function sendManual() {
        S.stretchTimer = null;
        S.stretchSentAt = Date.now();
        send({kind: 'set_stretch', mode: 'manual',
              black: levelFromSlider($id('fs-black').value), white: levelFromSlider($id('fs-white').value)});
    }

    function onLevelInput(moved) {
        var b = $id('fs-black');
        var w = $id('fs-white');
        var pair = orderSliders(Number(b.value), Number(w.value), moved);
        b.value = pair[0];
        w.value = pair[1];
        S.stretchHeldUntil = Date.now() + STRETCH_HOLD_MS;
        showLevels();
        if (S.stretchTimer === null) {
            var wait = Math.max(0, S.stretchSentAt + STRETCH_SEND_MS - Date.now());
            S.stretchTimer = setTimeout(sendManual, wait);
        }
    }

    function chooseStretch(mode) {
        if (mode === 'manual') {
            // start from the levels in the picture now, so it does not jump
            var st = S.stretch;
            var pair = st.black !== null ? [sliderFromLevel(st.black), sliderFromLevel(st.white)] : [0, SLIDER_MAX];
            pair = orderSliders(pair[0], pair[1], 'black');
            $id('fs-black').value = pair[0];
            $id('fs-white').value = pair[1];
            sendManual();
        } else {
            send({kind: 'set_stretch', mode: mode});
        }
    }

    function roiKey(roi) {
        return Array.isArray(roi) ? roi.join(',') : 'none';
    }

    function onMode(msg) {
        if (S.preview && S.mode && roiKey(msg.roi) !== S.preview.roiKey) {
            closeRegion();  // the region moved: capture drops a whole-sensor picture it was taking, with no reply
        }
        S.mode = msg;
        renderMode();
    }

    function openRegion() {
        if (S.preview || !canMoveRegion(S.mode)) {
            return;
        }
        if (!send({kind: 'preview'})) {
            toast(MSG_NOT_CONNECTED);
            return;
        }
        S.preview = {roiKey: roiKey(S.mode.roi)};
        show($id('fs-region'), true);
        show($id('fs-region-wait'), true);
        show($id('fs-region-pic'), false);
        show($id('fs-region-hint'), false);
    }

    function closeRegion() {
        S.preview = null;
        show($id('fs-region'), false);
    }

    var box = null;  // {x, y, w, h, W, H} in sensor px

    function onPreview(msg) {
        if (!S.preview || typeof msg.jpeg !== 'string' || !/^[A-Za-z0-9+/=]+$/.test(msg.jpeg)) {
            return;
        }
        var W = msg.width;
        var H = msg.height;
        if (!known(W) || !known(H) || W < 2 || H < 2) {
            closeRegion();
            return;
        }
        // the current region, or for a whole-frame picture (stills, or a sensor size capture did not know) the
        // size capture would start a region at, centred
        box = regionBox(W, H, S.mode ? S.mode.roi : null);
        box.W = W;
        box.H = H;
        $id('fs-region-img').src = 'data:image/jpeg;base64,' + msg.jpeg;
        placeBox();
        show($id('fs-region-wait'), false);
        show($id('fs-region-pic'), true);
        show($id('fs-region-hint'), true);
    }

    function placeBox() {
        var el = $id('fs-region-box');
        el.style.left = (box.x / box.W * 100) + '%';
        el.style.top = (box.y / box.H * 100) + '%';
        el.style.width = (box.w / box.W * 100) + '%';
        el.style.height = (box.h / box.H * 100) + '%';
    }

    function bindRegionDrag() {
        var el = $id('fs-region-box');
        var from = null;
        el.addEventListener('pointerdown', function (e) {
            if (!box) {
                return;
            }
            from = {cx: e.clientX, cy: e.clientY, x: box.x, y: box.y};
            try { el.setPointerCapture(e.pointerId); } catch (err) { /* not every browser */ }
            e.preventDefault();
        });
        el.addEventListener('pointermove', function (e) {
            if (!from) {
                return;
            }
            var k = box.W / ($id('fs-region-img').clientWidth || 1);
            box.x = Math.max(0, Math.min(box.W - box.w, from.x + (e.clientX - from.cx) * k));
            box.y = Math.max(0, Math.min(box.H - box.h, from.y + (e.clientY - from.cy) * k));
            placeBox();
        });
        el.addEventListener('pointerup', function () {
            if (!from) {
                return;
            }
            from = null;
            var even = function (v) { return Math.max(0, Math.floor(v / 2) * 2); };
            var roi = [even(box.x), even(box.y), even(box.w), even(box.h)];
            closeRegion();
            command({kind: 'set_region', roi: roi}, 'region');
        });
        el.addEventListener('pointercancel', function () { from = null; });
    }

    // ==== motor and hand-turned rigs =============================================================================

    // ---- loading signs and button spinners (Gitea issue 5) ------------------------------------------------------

    function renderPicWait() {
        show($id('fs-pic-wait'), S.session === 'active' && S.awaitFrame);
    }

    // A button's spinner: a daisyUI loading span before its words, and aria-busy.
    function spin(el, on) {
        if (!el) {
            return;
        }
        var sp = el.querySelector('.fs-spin');
        if (on && !sp) {
            sp = document.createElement('span');
            sp.className = 'fs-spin tw:loading tw:loading-spinner tw:loading-xs';
            sp.setAttribute('aria-hidden', 'true');
            el.insertBefore(sp, el.firstChild);
        } else if (!on && sp) {
            el.removeChild(sp);
        }
        if (el.getAttribute('aria-busy') !== String(!!on)) {
            el.setAttribute('aria-busy', String(!!on));
        }
    }

    // A button's words, leaving its spinner alone.
    function setLabel(el, text) {
        var span = el.querySelector('.fs-label');
        if (!span) {
            span = document.createElement('span');
            span.className = 'fs-label';
            el.textContent = '';
            el.appendChild(span);
        }
        setText(span, text);
    }

    // ==== lens, graph and autofocus ==============================================================================

    var NUDGES = {'fs-lens-in': -1, 'fs-lens-out': 1};   // the direction; the size is the Step size list's
    var MOVE_BTNS = ['fs-lens-in', 'fs-lens-out', 'fs-graph', 'fs-bestfit', 'fs-back'];

    // The Step size list's labels, in lens degrees from the last `lens` message.
    function renderStepSizes() {
        var sel = $id('fs-lens-size');
        if (!sel) {
            return;
        }
        var L = S.lens;
        Array.prototype.forEach.call(sel.options, function (o) {
            setText(o, stepLabel(o.value, L ? L[o.value] : null, L ? L.steps_per_lens_turn : null));
        });
    }

    function lensOk() {
        return S.motor.ok && S.lens !== null;
    }

    // A move or an autofocus is running: only Stop is offered (capture refuses a second move while one runs). The
    // autofocus fit stage has the lens at rest, so autofocus counts on its own.
    function lensBusy() {
        return (S.lens !== null && S.lens.moving === true) || S.af.running;
    }

    // This page sent a move capture has not started yet.
    function moveWaiting() {
        return MOVE_BTNS.some(function (b) { return pendingSpins(S.pending, b); });
    }

    function onLens(msg) {
        var prev = S.lens;
        S.lens = msg;
        var id = typeof msg.cmd_id === 'number' ? msg.cmd_id : null;
        if (id !== null) {
            S.highestCmd = Math.max(S.highestCmd, id);
        }
        if (msg.error && (!prev || prev.error !== msg.error || prev.cmd_id !== msg.cmd_id)) {
            toast(String(msg.error));
        }
        var list = S.pending;
        if (id !== null) {
            list = msg.error && !msg.moving ? pendingDrop(list, id) : pendingAnswered(list, id);
        }
        if (!msg.moving) {
            // the move has ended: its picture is the next one taken at rest here (reading.x), or a frame carrying
            // its id; expirePending gives up after a while
            list = list.map(function (p) {
                if (p.kind === 'motor' && !p.restAt && (p.answered || (id !== null && p.id <= id))) {
                    return Object.assign({}, p, {answered: true, rest: msg.position, restAt: Date.now()});
                }
                return p;
            });
            if (!S.af.running) {
                list = pendingDropKind(list, 'stop');
            }
        } else if (S.stars.length && !S.af.running &&
                   !list.some(function (p) { return p.kind === 'autofocus'; })) {
            S.checking = true;  // the lens moved after the pick: the Check step
        }
        setPending(list);
        renderLens();
    }

    // A reading taken at rest where a move ended shows that move.
    function motorShown(r) {
        if (typeof r.x !== 'number') {
            return;
        }
        setPending(S.pending.filter(function (p) {
            return !(p.kind === 'motor' && p.restAt && Math.abs(r.x - p.rest) < 0.5);
        }));
    }

    function onGraph(msg) {
        var pts = Array.isArray(msg.points) ? msg.points : [];
        S.graph = {
            measure: msg.measure || null,
            // everything capture kept is old: purple
            points: pts.slice(-GRAPH_POINTS_MAX).filter(function (p) {
                return Array.isArray(p) && known(p[0]) && known(p[2]);
            }).map(function (p) { return [p[0], p[1], p[2], 0]; }),
            fit: drawableFit(msg.fit)
        };
        setPending(pendingDropKind(S.pending, 'graph'));
        renderLens();
    }

    // `fit`: the fit's fields, or null to clear. Either shape is read: the fields at the top, or under `fit`.
    function onFit(msg) {
        var f = Object.prototype.hasOwnProperty.call(msg, 'fit') ? msg.fit : msg;
        S.graph.fit = drawableFit(f);
        renderLens();
    }

    function graphAdd(r) {
        if (!Array.isArray(r.points) || !r.points.length) {
            return;
        }
        if (S.graph.measure && r.measure && r.measure !== S.graph.measure) {
            return;  // a reading of the other measure: capture's `graph` starts the graph again
        }
        if (!S.graph.measure) {
            S.graph.measure = r.measure || null;
        }
        var born = Date.now();
        var pts = S.graph.points;
        r.points.forEach(function (p) {
            if (Array.isArray(p) && known(p[0]) && known(p[2])) {
                pts.push([p[0], p[1], p[2], born]);
            }
        });
        if (pts.length > GRAPH_POINTS_MAX) {
            pts.splice(0, pts.length - GRAPH_POINTS_MAX);
        }
        drawGraph();
    }

    function onAutofocus(msg) {
        var af = S.af;
        var list = pendingDropKind(S.pending, 'autofocus');
        if (known(msg.estimate_s) && (!af.running || !known(S.lastEstimate))) {
            S.lastEstimate = msg.estimate_s;  // a whole run's time, as the button's "about N s"; not a late one
        }
        if (msg.done === true || msg.stage === 'done') {
            af.running = false;
            af.failed = typeof msg.message === 'string' ? msg.message : '';
            var wasDone = af.done;
            af.done = !af.failed;
            if (af.done) {
                S.checking = true;
                if (!wasDone && $id('fs-lens-size')) {
                    $id('fs-lens-size').value = 'fine';  // at best focus the small steps are the useful ones
                }
            }
            list = pendingDropKind(list, 'stop');
        } else {
            var now = nowS();
            if (!af.running) {
                af.running = true;
                af.done = false;
                af.failed = '';
                af.t0 = now;
                af.estimate = known(msg.estimate_s) ? msg.estimate_s : null;
            } else if (known(msg.estimate_s)) {
                var left = secondsLeft(af.t0, af.estimate, now);
                if (left === null || secondsLeft(af.t0, msg.estimate_s, now) < left) {
                    af.estimate = msg.estimate_s;  // the time left may fall, never jump up
                }
            }
            af.stage = msg.stage || af.stage;
            af.stages = Array.isArray(msg.stages) ? msg.stages : af.stages;
            af.columns = known(msg.columns) ? msg.columns : af.columns;
        }
        setPending(list);
        renderLens();
    }

    function autofocusSeconds() {
        if (known(S.lastEstimate)) {
            return S.lastEstimate;
        }
        return autofocusEstimate(S.lens, S.mode ? S.mode.exposure : null);
    }

    // ---- the right column: header, graph, nudges, buttons ---------------------------------------------------------

    function advanced() {
        return root.classList.contains('fs-advanced');
    }

    function renderLens() {
        var on = S.session === 'active';
        var motor = S.motor.ok;
        // the graph waits for an autofocus (it holds the sweep's samples only); a watcher's panel holds only the graph
        var started = S.af.running || S.graph.points.length > 0;
        show($id('fs-lens'), on && motor && (!!$id('fs-af-btn') || (started && advanced())));
        show($id('fs-graph-panel'), on && motor && started);
        show($id('fs-hand'), on && !motor);
        var reason = $id('fs-motor-reason');
        setText(reason, !motor && S.motor.reason ? S.motor.reason : '');
        show(reason, !motor && !!S.motor.reason);
        renderSteps();
        if (!motor || !$id('fs-graph')) {
            return;
        }
        var L = S.lens;
        var r = S.reading;
        var contrast = S.graph.measure === 'contrast' || (!S.graph.measure && !!r && r.measure === 'contrast');
        var head = '';
        if (r && r.measure === 'stars' && typeof r.size === 'number') {
            head = 'Star size ' + r.size.toFixed(1) + ' px';
        } else if (r && r.measure === 'contrast' && typeof r.contrast === 'number') {
            head = 'Contrast score ' + (r.contrast >= 10 ? Math.round(r.contrast) : r.contrast.toFixed(1));
        }
        setText($id('fs-g-size'), head);
        var lens = '';
        if (L && known(L.position)) {
            lens = 'Lens ' + signed(L.position);
            if (L.moving && known(L.target)) {
                lens += ' (target ' + signed(L.target) + ')';
            }
        }
        setText($id('fs-g-lens'), lens);
        setText($id('fs-g-note'), L && L.moving && L.phase === 'backlash' ? MSG_BACKLASH : '');
        var fit = S.graph.fit;
        var label = (contrast ? 'Contrast score' : 'Star size') + ' against lens position' +
            (L && known(L.position) ? ', lens at ' + signed(L.position) + ' steps' : '') +
            (!contrast && fit && fit.ok ? ', best fit at ' + signed(fit.c) : '') +
            (S.controls ? '. Click or drag to move the lens.' : '.');
        if ($id('fs-graph').getAttribute('aria-label') !== label) {
            $id('fs-graph').setAttribute('aria-label', label);
        }
        renderButtons(contrast);
        drawGraph();
    }

    function renderExit() {
        var save = $id('fs-save');
        var cancel = $id('fs-cancel');
        if (!save || !cancel) {
            return;  // a watcher's page
        }
        var afSave = $id('fs-af-save');
        var look = exitButtons(S.controls, !!afSave && !afSave.hidden, lensBusy() || stepRunning(S), S.cancelling);
        show(save, !look.save.hidden);
        save.disabled = look.save.disabled;
        cancel.disabled = look.cancel.disabled;
        spin(cancel, look.cancel.busy);
        setLabel(cancel, look.cancel.label);
    }

    function renderButtons(contrast) {
        var af = $id('fs-af-btn');
        if (!af) {
            renderExit();
            return;  // a watcher's page: no lens controls
        }
        var L = S.lens;
        var busy = lensBusy();
        var ready = lensOk() && S.controls;
        var waitMove = moveWaiting() || tuneHoldsLens(S);  // the lens holds still for the tune too
        Object.keys(NUDGES).forEach(function (id) {
            var b = $id(id);
            b.disabled = !ready || busy || waitMove;
            spin(b, pendingSpins(S.pending, id));
        });
        renderStepSizes();
        var stopping = pendingSpins(S.pending, 'fs-af-btn');
        var saved = !busy && S.af.done;  // after a good run, Save is the big button and Autofocus a plain one
        af.classList.toggle('tw:btn-error', busy);
        af.classList.toggle('tw:btn-primary', !busy && !saved);
        var save = $id('fs-af-save');
        show(save, saved);
        save.disabled = !S.controls || stepRunning(S);
        if (busy) {
            setLabel(af, 'Stop');
            af.disabled = !ready;
        } else if (contrast) {
            setLabel(af, MSG_NEEDS_STARS);
            af.disabled = true;
        } else if (!S.stars.length) {
            // capture picks the stars first, and autofocus follows; in an autofocus plan that is already under way
            setLabel(af, 'Autofocus');
            af.disabled = !ready || waitMove ||
                (S.plan !== PLAN_PREVIEW && (S.picking || S.tuning || S.searching));
        } else {
            setLabel(af, autofocusLabel(autofocusSeconds(), saved));
            af.disabled = !ready || S.picking || S.tuning || stopping || waitMove;
        }
        spin(af, stopping);
        var fit = S.graph.fit;
        var best = $id('fs-bestfit');
        best.disabled = !ready || busy || waitMove || contrast || !(fit && fit.ok);
        spin(best, pendingSpins(S.pending, 'fs-bestfit'));
        var back = $id('fs-back');
        back.disabled = !ready || busy || waitMove || !L || L.previous === null || L.previous === undefined;
        spin(back, pendingSpins(S.pending, 'fs-back'));
        var clear = $id('fs-clear');
        var clearing = pendingSpins(S.pending, 'fs-clear');
        clear.disabled = !S.controls || S.af.running || clearing;
        spin(clear, clearing);
        renderExit();
    }

    function lensCommand(msg, btn) {
        if (!lensOk() || lensBusy() || moveWaiting() || tuneHoldsLens(S)) {
            return;
        }
        command(msg, 'motor', btn);
    }

    function nudge(btn) {
        var L = S.lens;
        var sel = $id('fs-lens-size');
        var size = sel ? sel.value : 'medium';
        if (!L || !known(L[size])) {
            return;
        }
        lensCommand({kind: 'nudge', steps: NUDGES[btn] * Math.max(1, Math.round(L[size]))}, btn);
    }

    function onAutofocusButton() {
        if (lensBusy()) {
            command({kind: 'stop'}, 'stop', 'fs-af-btn', false);
            return;
        }
        if (!lensOk()) {
            return;
        }
        if (!S.stars.length) {
            // no cmd_id: capture answers this press with the pick's progress, then the autofocus run's
            if (!send({kind: 'autofocus'})) {
                toast(MSG_NOT_CONNECTED);
                return;
            }
            S.plan = PLAN_AUTOFOCUS;
            S.af.failed = '';
            renderLens();
            return;
        }
        if (!S.af.done) {
            runAutofocus();
            return;
        }
        askConfirm(confirmText('again', true)).then(function (yes) {
            // the answer can come after the session moved on
            if (yes && S.session === 'active' && lensOk() && !lensBusy() && S.af.done) {
                runAutofocus();
            }
        });
    }

    function runAutofocus() {
        S.af.failed = '';
        command({kind: 'autofocus'}, 'autofocus', 'fs-af-btn');
    }

    // ---- the confirm dialog -------------------------------------------------------------------------------------

    var confirmDone = null;  // resolves the open question

    // Ask one of confirmText's questions: a promise of true for the second button. A question already open
    // answers no to this one.
    function askConfirm(q) {
        var dlg = $id('fs-confirm');
        if (!dlg || confirmDone) {
            return Promise.resolve(false);
        }
        setText($id('fs-confirm-t'), q.t);
        setText($id('fs-confirm-b'), q.b);
        setText($id('fs-confirm-no'), q.n);
        var yes = $id('fs-confirm-yes');
        setText(yes, q.y);
        yes.className = 'tw:btn tw:btn-sm ' + (q.danger ? 'tw:btn-error' : 'tw:btn-primary');
        dlg.returnValue = '';
        return new Promise(function (resolve) {
            confirmDone = resolve;
            dlg.showModal();
            $id('fs-confirm-no').focus();
        });
    }

    // The session started or ended under an open question: it no longer applies.
    function dropConfirm() {
        var dlg = $id('fs-confirm');
        if (dlg && dlg.open) {
            dlg.close('no');
        }
    }

    function bindConfirm() {
        var dlg = $id('fs-confirm');
        if (!dlg) {
            return;
        }
        dlg.addEventListener('close', function () {
            var done = confirmDone;
            confirmDone = null;
            if (done) {
                done(dlg.returnValue === 'yes');
            }
        });
        dlg.addEventListener('click', function (e) {
            if (e.target === dlg) {
                dlg.close('outside');  // a tap outside the box
            }
        });
        on('fs-confirm-yes', 'click', function () { dlg.close('yes'); });
        on('fs-confirm-no', 'click', function () { dlg.close('no'); });
    }

    function bindLens() {
        Object.keys(NUDGES).forEach(function (id) {
            on(id, 'click', function () { nudge(id); });
        });
        on('fs-af-btn', 'click', onAutofocusButton);
        on('fs-af-save', 'click', function () { send({kind: 'done'}); });
        on('fs-bestfit', 'click', function () {
            var f = S.graph.fit;
            if (f && f.ok) {
                lensCommand({kind: 'move_to', target: Math.round(f.c)}, 'fs-bestfit');
            }
        });
        on('fs-back', 'click', function () {
            if (S.lens && S.lens.previous !== null && S.lens.previous !== undefined) {
                lensCommand({kind: 'back'}, 'fs-back');
            }
        });
        on('fs-clear', 'click', function () { command({kind: 'clear_graph'}, 'graph', 'fs-clear', false); });
        bindGraph();
    }

    // ---- the graph ---------------------------------------------------------------------------------

    var G = {x0: 0, x1: 1, yt: 0, yb: 1, lo: -512, hi: 512, top: 4};  // the last drawn geometry, CSS px

    function graphLimit() {
        return S.lens && known(S.lens.limit) && S.lens.limit > 0 ? S.lens.limit : 512;
    }

    // The plot's x geometry from the canvas as it is now: a click must not trust the last paint (a hidden tab has no
    // animation frames, and the box may have changed size since).
    function graphGeomX() {
        var limit = graphLimit();
        G.lo = -limit;
        G.hi = limit;
        G.x0 = 34;
        G.x1 = Math.max(G.x0 + 1, $id('fs-graph').clientWidth - 8);
    }

    function stepAt(clientX) {
        graphGeomX();
        var rect = $id('fs-graph').getBoundingClientRect();
        var x = G.lo + (clientX - rect.left - G.x0) / (G.x1 - G.x0) * (G.hi - G.lo);
        return Math.min(G.hi, Math.max(G.lo, x));
    }

    function canDrag() {
        return S.controls && lensOk() && !lensBusy() && !moveWaiting() && !tuneHoldsLens(S);
    }

    // Click or drag: the lens moves when you let go, never during the drag.
    function bindGraph() {
        var c = $id('fs-graph');
        if (!c) {
            return;
        }
        c.addEventListener('pointerdown', function (e) {
            if (!canDrag() || (e.button !== undefined && e.button !== 0)) {
                return;
            }
            S.drag = stepAt(e.clientX);
            try { c.setPointerCapture(e.pointerId); } catch (err) { /* not every browser */ }
            e.preventDefault();
            drawGraph();
        });
        c.addEventListener('pointermove', function (e) {
            if (S.drag !== null) {
                S.drag = stepAt(e.clientX);
                drawGraph();
            }
        });
        c.addEventListener('pointerup', function (e) {
            if (S.drag === null) {
                return;
            }
            S.drag = null;
            var L = S.lens;
            var step = stepAt(e.clientX);  // sets G's x geometry first
            var pxPerStep = (G.x1 - G.x0) / (G.hi - G.lo);
            var reach = Array.isArray(L.reachable) ? L.reachable : [G.lo, G.hi];
            var t = graphTarget(step, reach, S.graph.fit, pxPerStep, SNAP_PX);
            if (canDrag() && t !== Math.round(L.position)) {
                lensCommand({kind: 'move_to', target: t}, 'fs-graph');
            }
            drawGraph();
        });
        c.addEventListener('pointercancel', function () {
            S.drag = null;
            drawGraph();
        });
    }

    function cssColor(name, fallback) {
        var v = getComputedStyle(root).getPropertyValue(name);
        return v && v.trim() ? v.trim() : fallback;
    }

    // Draw on the next animation frame; paintGraph asks again while a point is still fading.
    function drawGraph() {
        if (S.graphRaf === null) {
            S.graphRaf = requestAnimationFrame(function () {
                S.graphRaf = null;
                paintGraph();
            });
        }
    }

    function paintGraph() {
        var c = $id('fs-graph');
        if (!c || !c.clientWidth || S.session !== 'active' || !S.motor.ok) {
            return;
        }
        var dpr = window.devicePixelRatio || 1;
        var W = c.clientWidth;
        var H = c.clientHeight;
        if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
            c.width = Math.round(W * dpr);
            c.height = Math.round(H * dpr);
        }
        var ctx = c.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        var ink = cssColor('--color-base-content', '#9ca3af');
        var L = S.lens;
        var g = S.graph;
        var contrast = g.measure === 'contrast';
        var fit = contrast ? null : g.fit;  // a contrast graph has no curve and no band
        graphGeomX();
        G.yt = 16;
        G.yb = H - 20;
        G.top = graphTop(g.points.map(function (p) { return p[2]; }), fit, contrast ? 1 : 4);
        var xOf = function (x) { return G.x0 + (x - G.lo) / (G.hi - G.lo) * (G.x1 - G.x0); };
        var yOf = function (v) { return G.yb - Math.min(1.02, v / G.top) * (G.yb - G.yt); };
        var clampX = function (px) { return Math.min(G.x1, Math.max(G.x0, px)); };

        // frame, the inward end the lens cannot reach (the backlash take-up), axes
        ctx.lineWidth = 1;
        ctx.strokeStyle = ink;
        ctx.globalAlpha = 0.25;
        ctx.strokeRect(G.x0 + 0.5, G.yt + 0.5, G.x1 - G.x0 - 1, G.yb - G.yt - 1);
        if (L && Array.isArray(L.reachable) && L.reachable[0] > G.lo) {
            ctx.fillStyle = ink;
            ctx.globalAlpha = 0.08;
            ctx.fillRect(G.x0, G.yt, xOf(L.reachable[0]) - G.x0, G.yb - G.yt);
        }
        ctx.globalAlpha = 0.65;
        ctx.fillStyle = ink;
        ctx.font = '10px system-ui, sans-serif';
        ctx.textAlign = 'right';
        var step = niceStep(G.top / 3);
        for (var t = 0; t <= G.top + 1e-9; t += step) {
            ctx.fillText(contrast ? String(Math.round(t)) : String(Number(t.toFixed(2))), G.x0 - 4, yOf(t) + 3);
        }
        ctx.textAlign = 'left';
        ctx.fillText(contrast ? 'contrast · higher is sharper' : 'star size (px)', G.x0 + 4, G.yt - 4);
        ctx.textAlign = 'center';
        [G.lo, 0, G.hi].forEach(function (x) {
            ctx.textAlign = x === G.lo ? 'left' : x === G.hi ? 'right' : 'center';
            ctx.fillText(signed(x), xOf(x), G.yb + 13);
        });
        ctx.textAlign = 'right';
        ctx.fillText('steps', G.x1 - 34, G.yb + 13);

        // the sharp zone and the curve, plateau included
        if (fit) {
            if (fit.ok && Array.isArray(fit.band) && fit.band.length === 2) {
                ctx.globalAlpha = 0.16;
                ctx.fillStyle = '#4ade80';
                var b0 = clampX(xOf(fit.band[0]));
                var b1 = clampX(xOf(fit.band[1]));
                ctx.fillRect(b0, G.yt, Math.max(2, b1 - b0), G.yb - G.yt);
            }
            ctx.globalAlpha = fit.ok ? 0.95 : 0.5;
            ctx.strokeStyle = '#60a5fa';
            ctx.lineWidth = 2;
            ctx.setLineDash(fit.ok ? [] : [5, 4]);
            ctx.beginPath();
            for (var i = 0; i <= 240; i++) {
                var x = G.lo + (G.hi - G.lo) * i / 240;
                if (i) {
                    ctx.lineTo(xOf(x), yOf(fitModel(fit, x)));
                } else {
                    ctx.moveTo(xOf(x), yOf(fitModel(fit, x)));
                }
            }
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // points: the settled ones in one batch, the fading ones one by one, newest on top
        var now = Date.now();
        var fresh = [];
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = fadeColor(FADE_S);
        ctx.beginPath();
        g.points.forEach(function (p) {
            if ((now - p[3]) / 1000 < FADE_S) {
                fresh.push(p);
            } else {
                ctx.rect(xOf(p[0]) - 1.5, yOf(p[2]) - 1.5, 3, 3);
            }
        });
        ctx.fill();
        ctx.globalAlpha = 1;
        fresh.forEach(function (p) {
            ctx.fillStyle = fadeColor((now - p[3]) / 1000);
            ctx.fillRect(xOf(p[0]) - 2, yOf(p[2]) - 2, 4, 4);
        });

        // best fit
        if (fit && fit.ok) {
            var bx = clampX(xOf(fit.c));
            var right = bx > (G.x0 + G.x1) / 2;
            ctx.strokeStyle = '#4ade80';
            ctx.globalAlpha = 0.8;
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(Math.round(bx) + 0.5, G.yt);
            ctx.lineTo(Math.round(bx) + 0.5, G.yb);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = ink;
            ctx.textAlign = right ? 'right' : 'left';
            ctx.fillText(right ? 'best fit ' + signed(fit.c) + ' →' : '← best fit ' + signed(fit.c),
                         bx + (right ? -4 : 4), G.yb - 6);
        }

        // the focus line at the lens; while moving, a second line at the target; while dragging, where you let go
        if (L && known(L.position)) {
            var moving = L.moving && known(L.target) && Math.round(L.target) !== Math.round(L.position);
            var outward = moving && L.target > L.position;  // the two labels go on their own sides, apart
            vline(ctx, clampX(xOf(L.position)), '#4ade80', 2, [], 'lens', moving ? !outward : null);
            if (moving) {
                vline(ctx, clampX(xOf(L.target)), '#fbbf24', 1.5, [5, 3],
                      S.af.running && S.af.stage === 'start' ? 'scan start' : 'target', outward);
            }
        }
        if (S.drag !== null) {
            vline(ctx, clampX(xOf(S.drag)), '#fbbf24', 2, [], 'let go to move');
        }
        c.style.cursor = canDrag() ? 'crosshair' : 'default';
        if (fresh.length) {
            drawGraph();
        }
    }

    // A vertical line with its label to the right of it (rightSide true), to the left (false), or wherever it fits
    // (null). A label that would run off the plot goes to the other side.
    function vline(ctx, x, color, width, dash, label, rightSide) {
        var w = ctx.measureText(label).width + 6;
        var toRight = rightSide === true || ((rightSide === null || rightSide === undefined) && x <= G.x1 - 70);
        if (toRight && x + w > G.x1) {
            toRight = false;
        } else if (!toRight && x - w < G.x0) {
            toRight = true;
        }
        var right = !toRight;
        ctx.globalAlpha = 1;
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.setLineDash(dash);
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, G.yt);
        ctx.lineTo(Math.round(x) + 0.5, G.yb);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = color;
        ctx.textAlign = right ? 'right' : 'left';
        ctx.fillText(label, x + (right ? -4 : 4), G.yt + 11);
    }

    function niceStep(raw) {
        if (!(raw > 0)) {
            return 1;
        }
        var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
        var n = raw / mag;
        return (n > 5 ? 10 : n > 2 ? 5 : n > 1 ? 2 : 1) * mag;
    }

    // ---- the session's steps, and autofocus's own (Gitea issue 4) -------------------------------------------------

    var STEP_MARK = {done: '✓', current: '●', todo: '○', skipped: '○'};

    function renderSteps() {
        var ol = $id('fs-steps');
        if (!ol) {
            return;
        }
        var steps = sessionSteps({
            motor: S.motor.ok, stars: S.stars.length > 0, tuning: S.tuning || S.searching, picking: S.picking,
            afRunning: S.af.running, afDone: S.af.done, checking: S.checking, preview: S.plan === PLAN_PREVIEW
        });
        var key = JSON.stringify(steps);
        if (ol.getAttribute('data-key') !== key) {
            ol.setAttribute('data-key', key);
            while (ol.firstChild) {
                ol.removeChild(ol.firstChild);
            }
            steps.forEach(function (st) {
                var li = document.createElement('li');
                li.className = 'fs-step fs-step-' + st.state;
                if (st.state === 'current') {
                    li.setAttribute('aria-current', 'step');
                }
                var mark = document.createElement('span');
                mark.className = 'fs-step-mark';
                mark.setAttribute('aria-hidden', 'true');
                mark.textContent = STEP_MARK[st.state];
                li.appendChild(mark);
                li.appendChild(document.createTextNode(' ' + st.label));
                if (st.state === 'done') {
                    var sr = document.createElement('span');
                    sr.className = 'fs-sr';
                    sr.textContent = ' (done)';
                    li.appendChild(sr);
                }
                ol.appendChild(li);
            });
        }
        var current = steps.filter(function (st) { return st.state === 'current'; })[0];
        setText($id('fs-step-help'), current ? stepHelp(current.key, S.picking || S.af.running) : '');
        var af = S.af;
        show($id('fs-af'), af.running);
        setText($id('fs-af-msg'), af.running ? '' : af.failed);
        show($id('fs-af-msg'), !af.running && !!af.failed);
        if (!af.running) {
            return;
        }
        var stages = Array.isArray(af.stages) && af.stages.length ? af.stages : STAGES;
        var at = stages.indexOf(af.stage);
        setText($id('fs-af-title'), at < 0 ? 'Autofocus' :
            'Autofocus  ' + (at + 1) + ' of ' + stages.length + ': ' + stageWords(af.stage));
        var rows = autofocusRows(stages, af.stage, af.columns);
        var list = $id('fs-af-stages');
        var rkey = JSON.stringify(rows);
        if (list.getAttribute('data-key') !== rkey) {
            list.setAttribute('data-key', rkey);
            while (list.firstChild) {
                list.removeChild(list.firstChild);
            }
            rows.forEach(function (row) {
                var li = document.createElement('li');
                li.className = 'fs-step-' + row.state;
                if (row.state === 'current') {
                    li.setAttribute('aria-current', 'step');
                }
                li.textContent = STEP_MARK[row.state] + ' ' + row.words;
                list.appendChild(li);
            });
        }
        renderAutofocusTime();
    }

    // The tune's and the pick's bar, under the steps, with the step's words under it.
    function renderStepBar(msg) {
        var fill = stepBar(msg);
        var bar = $id('fs-step-bar');
        if (bar && fill !== null) {
            bar.value = fill;
            setText($id('fs-step-msg'), typeof msg.message === 'string' ? msg.message : '');
        }
        show($id('fs-step-prog'), fill !== null);
    }

    // The bar and "about N s left", counting down from the estimate between messages.
    function renderAutofocusTime() {
        var af = S.af;
        var bar = $id('fs-af-bar');
        if (!af.running || !bar) {
            return;
        }
        var now = nowS();
        var left = secondsLeft(af.t0, af.estimate, now);
        if (left === null) {
            bar.removeAttribute('value');  // indeterminate
            setText($id('fs-af-left'), '');
            return;
        }
        bar.value = af.estimate > 0 ? Math.round(Math.min(1, (now - af.t0) / af.estimate) * 100) : 100;
        setText($id('fs-af-left'), left >= 1 ? 'about ' + Math.ceil(left) + ' s left' : 'almost done');
    }

    // ---- the hand-turned rig's trace ----------------------------------------------------------------------------

    function traceReset(measure) {
        S.trace = [];
        S.best = null;
        S.traceMeasure = measure || null;
        drawTrace();
    }

    function traceAdd(r) {
        var v = null;
        if (r.measure === 'stars' && typeof r.size === 'number') {
            v = r.size;
        } else if (r.measure === 'contrast' && typeof r.contrast === 'number') {
            v = r.contrast;
        }
        if (r.measure !== S.traceMeasure) {
            traceReset(r.measure);
        }
        if (v === null || typeof r.capture_time !== 'number') {
            return;
        }
        S.trace.push([r.capture_time, v]);
        while (S.trace.length && S.trace[0][0] < r.capture_time - TRACE_S) {
            S.trace.shift();
        }
        var higher = r.measure === 'contrast';  // best: the smallest star size, the highest contrast score
        if (S.best === null || (higher ? v > S.best : v < S.best)) {
            S.best = v;
        }
        drawTrace();
    }

    function drawTrace() {
        var c = $id('fs-trace');
        if (!c || !c.clientWidth) {
            return;
        }
        var dpr = window.devicePixelRatio || 1;
        var W = c.clientWidth;
        var H = c.clientHeight;
        if (c.width !== Math.round(W * dpr)) {
            c.width = Math.round(W * dpr);
            c.height = Math.round(H * dpr);
        }
        var ctx = c.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        var pts = S.trace;
        var contrast = S.traceMeasure === 'contrast';
        var best = $id('fs-best');
        setText(best, S.best === null ? '' : 'Best so far: ' + (contrast ?
            'contrast score ' + Math.round(S.best) : S.best.toFixed(2) + ' px'));
        if (!pts.length) {
            return;
        }
        var lo = S.best;
        var hi = S.best;
        pts.forEach(function (p) { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); });
        var pad = Math.max((hi - lo) * 0.15, contrast ? 1 : 0.05);
        lo -= pad;
        hi += pad;
        var t1 = pts[pts.length - 1][0];
        var xOf = function (t) { return 4 + (W - 8) * (1 - (t1 - t) / TRACE_S); };
        var yOf = function (v) { return 6 + (H - 12) * (1 - (v - lo) / (hi - lo)); };
        ctx.strokeStyle = '#4ade80';
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(0, yOf(S.best));
        ctx.lineTo(W, yOf(S.best));
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.strokeStyle = '#60a5fa';
        ctx.lineWidth = 2;
        ctx.beginPath();
        pts.forEach(function (p, i) {
            if (i) {
                ctx.lineTo(xOf(p[0]), yOf(p[1]));
            } else {
                ctx.moveTo(xOf(p[0]), yOf(p[1]));
            }
        });
        ctx.stroke();
    }

    // ==== idle warning ===========================================================================================

    function renderWarn() {
        var on = S.session === 'active' && S.warnUntil !== null;
        show($id('fs-warn'), on);
        if (on) {
            var left = Math.max(0, Math.ceil((S.warnUntil - Date.now()) / 1000));
            setText($id('fs-warn-text'), (S.controls ? MSG_WARN : MSG_WARN_WATCHER).replace('{0}', String(left)));
        }
    }

    function keepGoing(force) {
        if (S.session !== 'active' || !S.controls) {
            return;
        }
        var now = Date.now();
        if (force || now - S.lastKeep >= KEEP_GOING_EVERY_MS) {
            if (send({kind: 'keep_going'})) {
                S.lastKeep = now;
            }
        }
    }

    // ==== live and idle views ====================================================================================

    function enterLive() {
        dropConfirm();
        if (S.session !== 'active') {
            // a new session: the lens count starts again. A rejoin keeps the graph; capture's `graph` and `lens`
            // replace it on joining.
            S.lens = null;
            S.af = {running: false, stage: null, stages: null, columns: null, t0: null, estimate: null, failed: '',
                    done: false};
            S.checking = false;
        }
        S.awaitFrame = true;
        S.session = 'active';
        S.drawnFrame = -1;
        S.captureTime = null;
        S.lastArrival = null;
        S.intervals = [];
        S.pending = [];
        S.reading = null;
        S.stars = [];
        S.picking = false;
        S.tuning = false;
        S.searching = false;
        S.cancelling = false;
        S.lastKeep = 0;
        traceReset(null);
        setText($id('fs-progress'), '');
        show($id('fs-ended'), false);
        show($id('fs-idle'), false);
        show($id('fs-live'), true);
        renderNumber();
        renderStarsUi();
        drawRings();
        renderPicWait();
        renderLens();
    }

    function leaveLive() {
        dropConfirm();
        S.session = 'idle';
        S.warnUntil = null;
        S.pending = [];
        closeRegion();
        setBig(false);
        show($id('fs-cam-pop'), false);
        show($id('fs-stretch-pop'), false);
        show($id('fs-live'), false);
        show($id('fs-idle'), true);
        S.graph = {measure: null, points: [], fit: null};
        S.lens = null;
        S.drag = null;
    }

    function renderControls() {
        renderStarsUi();
    }

    function renderIdleReason() {
        var reason = root.getAttribute('data-reason') || '';
        if (S.rig && typeof S.rig.reason === 'string' && S.rig.reason) {
            reason = S.rig.reason;
        }
        if (S.rig && S.rig.picture === 'stills' && reason) {
            reason = 'Still pictures: ' + reason;
        }
        setText($id('fs-idle-reason'), reason);
        show($id('fs-idle-reason'), !!reason);
    }

    var START_BUTTONS = [['focus-start', PLAN_PREVIEW, 'Start Live Preview'], ['focus-start-af', PLAN_AUTOFOCUS, 'Autofocus']];

    function setStartEnabled() {
        var open = !!S.ws && S.ws.readyState === WebSocket.OPEN;
        START_BUTTONS.forEach(function (sb) {
            var b = $id(sb[0]);
            if (b) {
                var look = startButton(open, S.starting !== false, S.starting === sb[1], sb[2]);
                // Autofocus needs a motor that can move the lens
                b.disabled = look.disabled || (sb[1] === PLAN_AUTOFOCUS && !S.motor.ok);
                spin(b, look.busy);
                setLabel(b, look.label);
            }
        });
        show($id('fs-idle-lens'), S.motor.configured);
        setText($id('fs-idle-hint'), S.motor.reason || MSG_PLAY_HINT);
    }

    function startSession(plan) {
        if (S.starting !== false) {
            return;
        }
        askConfirm(confirmText(plan === PLAN_PREVIEW ? 'start' : 'start_af', S.motor.ok)).then(function (yes) {
            // the answer can come after another page started a session
            if (yes && S.starting === false && S.session !== 'active') {
                sendStart(plan);
            }
        });
    }

    function sendStart(plan) {
        if (!send({kind: 'start', plan: plan})) {
            toast(MSG_NOT_CONNECTED);
            return;
        }
        S.starting = plan;
        setStartEnabled();
    }

    // Advanced shows the controls and details beyond the picture, the steps, the lens buttons, Save and Cancel.
    // Remembered per browser.
    function setAdvanced(on, remember) {
        root.classList.toggle('fs-advanced', on);
        var box = $id('fs-advanced');
        if (box) {
            box.checked = on;
        }
        if (remember) {
            try {
                window.localStorage.setItem(ADVANCED_KEY, on ? '1' : '0');
            } catch (e) {
                // private window or blocked storage: the choice lasts this page only
            }
        }
        renderLens();
        if (S.session === 'active') {
            drawRings();
            drawTrace();
        }
    }

    function storedAdvanced() {
        try {
            return window.localStorage.getItem(ADVANCED_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    // A start is answered by a state (the session, or idle when it failed), an error, or the link closing.
    function startAnswered() {
        if (S.starting !== false) {
            S.starting = false;
            setStartEnabled();
        }
    }

    // ==== start-up ===============================================================================================

    function on(id, event, fn) {
        var el = $id(id);
        if (el) {
            el.addEventListener(event, fn);
        }
    }

    function init() {
        on('focus-start', 'click', function () { startSession(PLAN_PREVIEW); });
        on('focus-start-af', 'click', function () { startSession(PLAN_AUTOFOCUS); });
        on('fs-advanced', 'change', function () { setAdvanced(this.checked, true); });
        setAdvanced(storedAdvanced(), false);
        on('fs-save', 'click', function () { send({kind: 'done'}); });
        bindConfirm();
        on('fs-cancel', 'click', function () {
            if (S.cancelling) {
                return;
            }
            askConfirm(confirmText('cancel', lensOk())).then(function (yes) {
                if (yes && !S.cancelling && S.session === 'active' && send({kind: 'cancel'})) {
                    S.cancelling = true;
                    renderExit();
                }
            });
        });
        on('fs-keep-going', 'click', function () { keepGoing(true); });
        on('fs-repick', 'click', function () { send({kind: 'pick_stars'}); show($id('fs-stars-pop'), false); });
        on('fs-stars-chip', 'click', function () {
            var pop = $id('fs-stars-pop');
            show(pop, pop.hidden);
            this.setAttribute('aria-expanded', String(!pop.hidden));
        });
        on('fs-snr', 'input', function () {
            S.snrHeld = Number(this.value);
            setText($id('fs-snr-v'), this.value);
            clearTimeout(S.snrTimer);
            drawRings();
            renderStarsUi();
        });
        on('fs-snr', 'change', function () {
            var v = Number(this.value);
            send({kind: 'min_snr', value: v});
            clearTimeout(S.snrTimer);
            S.snrTimer = setTimeout(function () { S.snrHeld = null; renderStarsUi(); drawRings(); }, 2000);
        });
        on('fs-exp-btn', 'click', openCamera);
        on('fs-gain-btn', 'click', openCamera);
        on('fs-cam-close', 'click', function () { show($id('fs-cam-pop'), false); });
        on('fs-exp', 'input', function () { camTouched.exp = true; showCamera(); });
        on('fs-gain', 'input', function () { camTouched.gain = true; showCamera(); });
        on('fs-apply', 'click', applyCamera);
        on('fs-stretch-btn', 'click', openStretch);
        on('fs-stretch-close', 'click', function () {
            show($id('fs-stretch-pop'), false);
            $id('fs-stretch-btn').setAttribute('aria-expanded', 'false');
        });
        ['auto', 'manual', 'off'].forEach(function (m) {
            on('fs-stretch-' + m, 'click', function () { chooseStretch(m); });
        });
        on('fs-relevel', 'click', function () { send({kind: 'set_stretch', mode: 'auto', relevel: true}); });
        on('fs-tune', 'click', function () { command({kind: 'tune'}, 'tune', 'fs-tune', false); });
        on('fs-black', 'input', function () { onLevelInput('black'); });
        on('fs-white', 'input', function () { onLevelInput('white'); });
        on('fs-region-btn', 'click', openRegion);
        on('fs-region-cancel', 'click', closeRegion);
        if ($id('fs-region-box')) {
            bindRegionDrag();
        }
        on('fs-pic', 'click', onPictureTap);
        on('fs-shrink', 'click', function (e) { e.stopPropagation(); setBig(false); });
        bindLens();

        // any click or key press on an admin's page counts as touching it, at most once every 30 s
        document.addEventListener('click', function () { keepGoing(false); }, true);
        document.addEventListener('keydown', function () { keepGoing(false); }, true);

        window.addEventListener('resize', function () { drawRings(); drawTrace(); drawGraph(); });
        setInterval(function () {
            if (S.session === 'active') {
                expirePending();
                renderStatus();
                renderWarn();
                renderAutofocusTime();
            }
        }, 100);

        renderIdleReason();
        setStartEnabled();
        connect();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
