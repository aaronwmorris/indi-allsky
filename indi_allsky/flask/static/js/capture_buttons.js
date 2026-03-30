/* Camera controls for indi-allsky — unified live controls via picamera2 daemon.
 * All changes apply immediately to the live stream and capture.
 */

// Toast notification helper
function showToast(msg, type) {
    type = type || "info";
    var id = "toast-" + Date.now();
    var bgClass = type === "success" ? "bg-success" : type === "danger" ? "bg-danger" : "bg-info";
    var html = '<div id="' + id + '" class="toast ' + bgClass + ' text-white border-0" role="alert">'
        + '<div class="d-flex"><div class="toast-body" style="white-space:pre-wrap;font-size:0.85rem">' + msg + '</div>'
        + '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>';
    var container = document.getElementById("toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "toast-container";
        container.className = "toast-container position-fixed top-0 end-0 p-3";
        container.style.zIndex = "9999";
        document.body.appendChild(container);
    }
    container.insertAdjacentHTML("beforeend", html);
    var el = document.getElementById(id);
    if (typeof bootstrap !== "undefined") new bootstrap.Toast(el, {delay: 3000}).show();
}

// ---- Slider definitions ----
var sliderDefs = [
    {id: "gain",       label: "Gain",          min: 0,    max: 100,      step: 0.5,   dec: 1},
    {id: "exposure",   label: "Exposure (s)",   min: 0,    max: 60,       step: 0.1,   dec: 2},
    {id: "brightness", label: "Brightness",     min: -1.0, max: 1.0,      step: 0.05,  dec: 2},
    {id: "contrast",   label: "Contrast",       min: 0,    max: 4.0,      step: 0.1,   dec: 1},
    {id: "target_adu", label: "Target ADU",     min: 10,   max: 224,      step: 5,     dec: 0},
    {id: "quality",    label: "JPEG Quality",   min: 10,   max: 100,      step: 5,     dec: 0},
];

var debounceTimer = null;

function buildControlsHTML() {
    var html = '';
    html += '<div class="mb-2"><strong class="text-info small">Camera Controls</strong>';
    html += ' <span id="ctrl-status" class="text-light small ms-2" style="opacity:0;transition:opacity 0.3s">Applying...</span></div>';

    sliderDefs.forEach(function(s) {
        html += buildSlider(s);
    });

    // AWB mode
    html += '<div class="row g-1 mb-1 align-items-center">';
    html += '<div class="col-3 text-end"><label class="form-label text-light small mb-0">AWB</label></div>';
    html += '<div class="col-6"><select id="ctrl-awb" class="form-select form-select-sm bg-dark text-light py-0" style="font-size:0.75rem" onchange="scheduleApply()">';
    ["auto","incandescent","tungsten","fluorescent","indoor","daylight","cloudy"].forEach(function(m) {
        html += '<option value="' + m + '"' + (m === "auto" ? " selected" : "") + '>' + m.charAt(0).toUpperCase() + m.slice(1) + '</option>';
    });
    html += '</select></div></div>';

    // Stream resolution
    html += '<div class="row g-1 mb-1 align-items-center">';
    html += '<div class="col-3 text-end"><label class="form-label text-light small mb-0">Resolution</label></div>';
    html += '<div class="col-6"><select id="ctrl-resolution" class="form-select form-select-sm bg-dark text-light py-0" style="font-size:0.75rem" onchange="changeResolution()">';
    html += '<option value="640x480" selected>640x480</option>';
    html += '<option value="1280x720">1280x720</option>';
    html += '<option value="1920x1080">1920x1080</option>';
    html += '</select></div></div>';

    // OSD toggle
    html += '<div class="row g-1 mb-1 align-items-center">';
    html += '<div class="col-3 text-end"><label class="form-label text-light small mb-0">OSD</label></div>';
    html += '<div class="col-6"><div class="form-check form-switch">';
    html += '<input class="form-check-input" type="checkbox" id="ctrl-osd" checked onchange="toggleOSD()">';
    html += '<label class="form-check-label text-light small" for="ctrl-osd">Show overlay</label>';
    html += '</div></div></div>';

    return html;
}

function toggleOSD() {
    var on = document.getElementById("ctrl-osd").checked;
    $.ajax({
        type: "GET",
        url: "/indi-allsky/api/stream/update?osd=" + (on ? "1" : "0"),
        timeout: 10000,
    });
}

function changeResolution() {
    var sel = document.getElementById("ctrl-resolution");
    if (!sel) return;
    var parts = sel.value.split("x");
    var w = parseInt(parts[0]), h = parseInt(parts[1]);
    $.ajax({
        type: "GET",
        url: "/indi-allsky/api/stream/update?stream_width=" + w + "&stream_height=" + h,
        timeout: 10000,
        success: function() {
            var status = document.getElementById("ctrl-status");
            if (status) { status.textContent = "Resolution changed"; status.style.opacity = "1"; }
            setTimeout(function() { if (status) status.style.opacity = "0"; }, 2000);
        },
    });
}

// Load modes from daemon and populate dropdown
function loadModes() {
    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/modes", timeout: 10000,
        success: function(data) {
            var sel = document.getElementById("ctrl-resolution");
            if (!sel || !data.modes) return;
            // Add hardware modes
            sel.innerHTML = "";
            // Software downscale options
            var sw = [
                {w: 640, h: 480, label: "640x480 (fast)"},
                {w: 1280, h: 720, label: "1280x720 (HD)"},
                {w: 1920, h: 1080, label: "1920x1080 (FHD)"},
            ];
            // Add native sensor modes
            data.modes.forEach(function(m) {
                if (m.width && m.height) {
                    sw.push({w: m.width, h: m.height,
                        label: m.width + "x" + m.height + " (native" + (m.fps ? " " + Math.round(m.fps) + "fps" : "") + ")"});
                }
            });
            // Deduplicate
            var seen = {};
            sw.forEach(function(r) {
                var key = r.w + "x" + r.h;
                if (seen[key]) return;
                seen[key] = true;
                var opt = document.createElement("option");
                opt.value = r.w + "x" + r.h;
                opt.textContent = r.label;
                if (r.w === data.stream_width && r.h === data.stream_height) opt.selected = true;
                sel.appendChild(opt);
            });
        },
    });
}

function buildSlider(s) {
    var sliderId = "ctrl-" + s.id;
    var valId = "val-" + s.id;
    var defVal = (s.id === "gain") ? 8 : (s.id === "exposure") ? 5 : (s.id === "target_adu") ? 75 : (s.id === "quality") ? 95 : (s.id === "brightness") ? 0 : 1;

    var h = '<div class="row g-1 mb-1 align-items-center">';
    h += '<div class="col-3 text-end"><label class="form-label text-light small mb-0" for="' + sliderId + '">' + s.label + '</label></div>';
    h += '<div class="col-6"><input type="range" class="form-range" style="height:16px" id="' + sliderId + '" ';
    h += 'min="' + s.min + '" max="' + s.max + '" step="' + s.step + '" value="' + defVal + '" ';
    h += 'oninput="onSliderInput(\'' + s.id + '\')">';
    h += '</div>';
    h += '<div class="col-3"><span id="' + valId + '" class="text-white small">' + defVal.toFixed(s.dec) + '</span></div>';
    h += '</div>';
    return h;
}

function onSliderInput(id) {
    var def = sliderDefs.find(function(s) { return s.id === id; });
    if (!def) return;
    var el = document.getElementById("ctrl-" + id);
    var val = parseFloat(el.value);
    document.getElementById("val-" + id).textContent = val.toFixed(def.dec);
    scheduleApply();
}

function scheduleApply() {
    if (debounceTimer) clearTimeout(debounceTimer);
    var status = document.getElementById("ctrl-status");
    if (status) status.style.opacity = "1";
    debounceTimer = setTimeout(function() {
        applySettings();
    }, 500);
}

function applySettings() {
    var params = {};
    sliderDefs.forEach(function(s) {
        var el = document.getElementById("ctrl-" + s.id);
        if (el) params[s.id] = parseFloat(el.value);
    });
    var awb = document.getElementById("ctrl-awb");
    if (awb) params.awb = awb.value;

    // Send to daemon via the stream update API
    var qs = Object.keys(params).map(function(k) {
        if (k === "exposure") return "shutter=" + Math.round(params[k] * 1000000);
        return k + "=" + params[k];
    }).join("&");

    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/update?" + qs, timeout: 10000,
        success: function() {
            var status = document.getElementById("ctrl-status");
            if (status) {
                status.textContent = "Applied";
                setTimeout(function() { status.style.opacity = "0"; }, 1000);
            }
        },
        error: function() {
            var status = document.getElementById("ctrl-status");
            if (status) { status.textContent = "Failed"; status.style.opacity = "1"; }
        },
    });
}

// Load sensor info to set gain range
function loadSensorInfo() {
    $.ajax({
        type: "GET", url: "/indi-allsky/api/sensor_info", timeout: 10000,
        success: function(data) {
            if (data.gain_max) {
                var el = document.getElementById("ctrl-gain");
                if (el) el.max = data.gain_max;
            }
        },
    });
}

// ---- Live View toggle ----
var liveLoopActive = window.liveLoopActive || false;

function toggleLiveLoop() {
    if (!window.player) return;
    if (liveLoopActive) {
        window.player.disconnect();
        liveLoopActive = false;
        window.liveLoopActive = false;
        var btn = document.getElementById("btn-live-loop");
        if (btn) { btn.textContent = "Live View"; btn.className = "btn btn-outline-success btn-sm me-2"; }
        $("#live-status").text("Stopped");
    } else {
        window.player.connect();
        liveLoopActive = true;
        window.liveLoopActive = true;
        var btn = document.getElementById("btn-live-loop");
        if (btn) { btn.textContent = "Stop Live"; btn.className = "btn btn-outline-danger btn-sm me-2"; }
        $("#live-status").text("");
    }
}

// ---- Capture One ----
function captureOne() {
    $("#live-status").text("Capturing...");
    $.ajax({
        type: "GET", url: "/indi-allsky/api/capture_one", timeout: 30000,
        success: function() { $("#live-status").text("Captured!"); setTimeout(function() { $("#live-status").text(""); }, 3000); },
        error: function() { $("#live-status").text("Capture failed"); },
    });
}

// Init: inject controls into the page
$(document).ready(function() {
    var target = document.getElementById("slider-panel");
    if (target) {
        target.innerHTML = buildControlsHTML();
        loadSensorInfo();
        loadModes();
    }
    // Update live button state if auto-connected
    if (window.liveLoopActive) {
        var btn = document.getElementById("btn-live-loop");
        if (btn) { btn.textContent = "Stop Live"; btn.className = "btn btn-outline-danger btn-sm me-2"; }
    }
});
