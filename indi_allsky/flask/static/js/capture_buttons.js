/* indi-allsky live capture controls with MJPEG streaming + config sliders */
var liveLoopActive = false;
var configLoaded = false;

/* ---- Toast popup for errors ---- */
function showToast(msg, type) {
    type = type || "danger";
    var toastId = "allsky-toast-" + Date.now();
    var html = '<div id="' + toastId + '" class="toast align-items-center text-bg-' + type + ' border-0 show" role="alert" '
        + 'style="position:fixed;top:20px;right:20px;z-index:9999;min-width:350px;max-width:500px">'
        + '<div class="d-flex"><div class="toast-body" style="white-space:pre-wrap;font-size:0.85rem">' + msg + '</div>'
        + '<button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="document.getElementById(\'' + toastId + '\').remove()"></button>'
        + '</div></div>';
    var container = document.getElementById("allsky-toast-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "allsky-toast-container";
        container.style.cssText = "position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px";
        document.body.appendChild(container);
    }
    container.insertAdjacentHTML("beforeend", html);
    setTimeout(function() {
        var el = document.getElementById(toastId);
        if (el) el.remove();
    }, 15000);
}

/* ---- Slider definitions ---- */
var sliderDefs = [
    /* Config sliders (saved to indi-allsky config DB) */
    {id: "NIGHT_GAIN",        label: "Night Gain",       min: 0, max: 22.26, step: 0.5,  dec: 1, group: "config"},
    {id: "MOONMODE_GAIN",     label: "Moon Gain",        min: 0, max: 22.26, step: 0.5,  dec: 1, group: "config"},
    {id: "DAY_GAIN",          label: "Day Gain",         min: 0, max: 22.26, step: 0.5,  dec: 1, group: "config"},
    {id: "CCD_EXPOSURE_MAX",  label: "Exposure Max (s)", min: 0.1, max: 60, step: 0.5,   dec: 1, group: "config"},
    {id: "CCD_EXPOSURE_DEF",  label: "Exposure Def (s)", min: 0.001, max: 30, step: 0.1, dec: 2, group: "config"},
    {id: "TARGET_ADU",        label: "Target ADU Night", min: 10, max: 200, step: 5,     dec: 0, group: "config"},
    {id: "TARGET_ADU_DAY",    label: "Target ADU Day",   min: 10, max: 200, step: 5,     dec: 0, group: "config"},
    {id: "SATURATION_FACTOR", label: "Saturation",       min: 0, max: 3.0, step: 0.05,   dec: 2, group: "config"},
    {id: "GAMMA_CORRECTION",  label: "Gamma",            min: 0.1, max: 3.0, step: 0.05, dec: 2, group: "config"},
    {id: "SHARPEN_AMOUNT",    label: "Sharpen",          min: 0, max: 5.0, step: 0.1,    dec: 1, group: "config"},

    /* Live-only sliders (passed to rpicam-vid, not saved to config) */
    {id: "live_shutter",    label: "Shutter (us)",  min: 0, max: 30000000, step: 10000, dec: 0, group: "live"},
    {id: "live_gain",       label: "Gain",          min: 0, max: 22.26,    step: 0.5,   dec: 1, group: "live"},
    {id: "live_brightness", label: "Brightness",    min: -1.0, max: 1.0,   step: 0.05,  dec: 2, group: "live"},
    {id: "live_contrast",   label: "Contrast",      min: 0, max: 3.0,      step: 0.1,   dec: 1, group: "live"},
    {id: "live_saturation", label: "Saturation",    min: 0, max: 3.0,      step: 0.1,   dec: 1, group: "live"},
    {id: "live_sharpness",  label: "Sharpness",     min: 0, max: 5.0,      step: 0.1,   dec: 1, group: "live"},
];

/* ---- Build slider UI ---- */
function buildSliderPanel() {
    var container = document.getElementById("slider-panel");
    if (!container) return;

    var html = "";

    /* Config sliders section */
    html += '<div class="mb-1"><strong class="text-info small">IMX415 Camera Settings</strong> <span class="text-muted small">(Allsky Config)</span>';
    html += ' <button class="btn btn-outline-warning btn-sm ms-2 py-0 px-1" style="font-size:0.7rem" onclick="saveConfig()">Save</button>';
    html += ' <button class="btn btn-outline-secondary btn-sm ms-2 py-0 px-1" style="font-size:0.7rem" onclick="loadConfig()">Reload</button>';
    html += ' <span id="config-status" class="text-muted small ms-2"></span></div>';
    html += '<div class="text-muted small mb-2" style="font-size:0.7rem">Gain range: 0&ndash;22.26 (analog max). Changes saved here persist and apply after allsky restart.</div>';
    sliderDefs.forEach(function(s) {
        if (s.group !== "config") return;
        html += sliderRow(s);
    });

    /* Live sliders section */
    html += '<div class="mt-3 mb-1"><strong class="text-success small">Live Camera Controls</strong> <span class="text-muted small">(rpicam-vid stream)</span>';
    html += ' <label class="form-check-label text-muted small ms-3"><input type="checkbox" id="chk-manual-exp" class="form-check-input me-1" onchange="toggleManualExposure()">Manual Exposure</label>';
    html += '</div>';
    html += '<div class="text-muted small mb-2" style="font-size:0.7rem">Override camera params during Live View. Changes apply instantly (restarts stream). Not saved to config.</div>';
    sliderDefs.forEach(function(s) {
        if (s.group !== "live") return;
        html += sliderRow(s);
    });

    /* AWB dropdown */
    html += '<div class="row g-1 mb-1"><div class="col-3 text-end"><label class="form-label text-muted small mb-0">AWB</label></div>';
    html += '<div class="col-6"><select id="live_awb" class="form-select form-select-sm bg-dark text-light py-0" style="font-size:0.75rem" disabled>';
    ["auto","incandescent","tungsten","fluorescent","indoor","daylight","cloudy"].forEach(function(m) {
        html += '<option value="' + m + '"' + (m === "auto" ? " selected" : "") + '>' + m + '</option>';
    });
    html += '</select></div></div>';

    /* Denoise dropdown */
    html += '<div class="row g-1 mb-1"><div class="col-3 text-end"><label class="form-label text-muted small mb-0">Denoise</label></div>';
    html += '<div class="col-6"><select id="live_denoise" class="form-select form-select-sm bg-dark text-light py-0" style="font-size:0.75rem" disabled>';
    ["auto","off","cdn_off","cdn_fast","cdn_hq"].forEach(function(m) {
        html += '<option value="' + m + '"' + (m === "auto" ? " selected" : "") + '>' + m + '</option>';
    });
    html += '</select></div></div>';

    /* Framerate */
    html += '<div class="row g-1 mb-1"><div class="col-3 text-end"><label class="form-label text-muted small mb-0">Framerate</label></div>';
    html += '<div class="col-6"><select id="live_framerate" class="form-select form-select-sm bg-dark text-light py-0" style="font-size:0.75rem">';
    [1, 2, 5, 10, 15, 24, 30].forEach(function(f) {
        html += '<option value="' + f + '"' + (f === 10 ? " selected" : "") + '>' + f + ' fps</option>';
    });
    html += '</select></div></div>';

    /* Apply button for live settings */
    html += '<div class="row g-1 mt-2"><div class="col-3"></div><div class="col-6">';
    html += '<button class="btn btn-outline-success btn-sm w-100" onclick="applyLiveSettings()" id="btn-apply-live">Apply to Stream</button>';
    html += '</div></div>';

    container.innerHTML = html;

    /* Disable live sliders initially */
    sliderDefs.forEach(function(s) {
        if (s.group === "live") {
            var el = document.getElementById("slider-" + s.id);
            if (el) el.disabled = true;
        }
    });
}

function sliderRow(s) {
    var valId = "val-" + s.id;
    var sliderId = "slider-" + s.id;
    var defVal = s.min;
    if (s.id === "live_contrast") defVal = 1.0;
    if (s.id === "live_saturation") defVal = 1.0;
    if (s.id === "live_sharpness") defVal = 1.0;

    var h = '<div class="row g-1 mb-1 align-items-center">';
    h += '<div class="col-3 text-end"><label class="form-label text-muted small mb-0" for="' + sliderId + '">' + s.label + '</label></div>';
    h += '<div class="col-6"><input type="range" class="form-range" style="height:16px" id="' + sliderId + '" ';
    h += 'min="' + s.min + '" max="' + s.max + '" step="' + s.step + '" value="' + defVal + '" ';
    h += 'oninput="sliderChanged(\'' + s.id + '\')">';
    h += '</div>';
    h += '<div class="col-3"><span id="' + valId + '" class="text-light small">' + defVal.toFixed(s.dec) + '</span></div>';
    h += '</div>';
    return h;
}

function sliderChanged(id) {
    var def = sliderDefs.find(function(s) { return s.id === id; });
    if (!def) return;
    var el = document.getElementById("slider-" + id);
    var val = parseFloat(el.value);
    document.getElementById("val-" + id).textContent = val.toFixed(def.dec);
}

function toggleManualExposure() {
    var manual = document.getElementById("chk-manual-exp").checked;
    sliderDefs.forEach(function(s) {
        if (s.group === "live") {
            var el = document.getElementById("slider-" + s.id);
            if (el) el.disabled = !manual;
        }
    });
    document.getElementById("live_awb").disabled = !manual;
    document.getElementById("live_denoise").disabled = !manual;
}

/* ---- Config load/save ---- */
function loadConfig() {
    $.ajax({
        type: "GET", url: "/indi-allsky/api/config_get", timeout: 10000,
        success: function(data) {
            sliderDefs.forEach(function(s) {
                if (s.group !== "config") return;
                if (data[s.id] !== undefined) {
                    var el = document.getElementById("slider-" + s.id);
                    if (el) {
                        el.value = data[s.id];
                        document.getElementById("val-" + s.id).textContent = parseFloat(data[s.id]).toFixed(s.dec);
                    }
                }
            });
            configLoaded = true;
            $("#config-status").text("Loaded").fadeIn().delay(2000).fadeOut();
        },
        error: function() { $("#config-status").text("Load failed"); },
    });
}

function saveConfig() {
    var payload = {};
    sliderDefs.forEach(function(s) {
        if (s.group !== "config") return;
        var el = document.getElementById("slider-" + s.id);
        if (el) payload[s.id] = parseFloat(el.value);
    });
    $("#config-status").text("Saving...");
    $.ajax({
        type: "POST", url: "/indi-allsky/api/config_set",
        contentType: "application/json", data: JSON.stringify(payload), timeout: 10000,
        success: function() {
            $("#config-status").text("Saved! Restart allsky to apply.").fadeIn();
            setTimeout(function() { $("#config-status").text(""); }, 5000);
        },
        error: function() { $("#config-status").text("Save failed"); },
    });
}

/* ---- Build live params query string ---- */
function getLiveParams() {
    var params = [];
    var manual = document.getElementById("chk-manual-exp");
    if (manual && manual.checked) {
        sliderDefs.forEach(function(s) {
            if (s.group !== "live") return;
            var el = document.getElementById("slider-" + s.id);
            if (!el) return;
            var val = parseFloat(el.value);
            var paramName = s.id.replace("live_", "");
            if (paramName === "shutter" && val > 0) params.push(paramName + "=" + Math.round(val));
            else if (paramName === "gain" && val > 0) params.push(paramName + "=" + val);
            else if (paramName === "brightness" && val !== 0) params.push(paramName + "=" + val);
            else if (paramName === "contrast" && val !== 1.0) params.push(paramName + "=" + val);
            else if (paramName === "saturation" && val !== 1.0) params.push(paramName + "=" + val);
            else if (paramName === "sharpness" && val !== 1.0) params.push(paramName + "=" + val);
        });
        var awb = document.getElementById("live_awb");
        if (awb && awb.value !== "auto") params.push("awb=" + awb.value);
        var denoise = document.getElementById("live_denoise");
        if (denoise && denoise.value !== "auto") params.push("denoise=" + denoise.value);
    }
    var framerate = document.getElementById("live_framerate");
    if (framerate) params.push("framerate=" + framerate.value);
    return params.join("&");
}

/* ---- Apply live settings to running stream ---- */
function applyLiveSettings() {
    if (!liveLoopActive) {
        $("#live-status").text("Start Live View first");
        setTimeout(function() { $("#live-status").text(""); }, 3000);
        return;
    }
    var params = getLiveParams();
    $("#live-status").text("Updating stream...");
    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/update?" + params, timeout: 10000,
        success: function(rdata) {
            var mode = (typeof player !== "undefined" && player !== null) ? "WebSocket" : "MJPEG";
            $("#live-status").text("Stream updated (" + (rdata.clients || 0) + " viewers)");
            setTimeout(function() { if (liveLoopActive) $("#live-status").text("Live - " + mode + " stream"); }, 3000);
            // Reconnect the player to pick up the restarted stream
            if (typeof player !== "undefined" && player !== null) {
                player.reconnect();
            } else {
                refreshStreamSrc();
            }
        },
        error: function(xhr) {
            var msg = xhr.responseJSON ? xhr.responseJSON.error : "Update failed (HTTP " + xhr.status + ")";
            $("#live-status").text("Update failed");
            showToast("Stream update failed:\n" + msg, "danger");
        },
    });
}

/* ---- Capture One ---- */
function captureOne() {
    var btn = document.getElementById("btn-capture-one");
    btn.disabled = true;
    btn.textContent = "Capturing...";
    $("#live-status").text("Capturing...");
    var params = getLiveParams();
    $.ajax({
        type: "GET", url: "/indi-allsky/api/capture_one?" + params, timeout: 45000,
        success: function(rdata) {
            btn.disabled = false; btn.textContent = "Capture One";
            $("#live-status").text("");
            if (rdata.url) {
                var img = new Image();
                img.onload = function() {
                    $("#latest-image").attr("src", this.src);
                    $("#loop-image").attr("src", this.src);
                };
                img.src = rdata.url;
                $("#message").html("Manual capture complete");
            }
            // If stream was running, it will be restarted by the backend
            if (liveLoopActive) {
                setTimeout(function() { refreshStreamSrc(); }, 1000);
            }
        },
        error: function(xhr) {
            btn.disabled = false; btn.textContent = "Capture One";
            var msg = xhr.responseJSON ? xhr.responseJSON.error : "Capture failed (HTTP " + xhr.status + ")";
            $("#live-status").text("Capture failed");
            showToast("Capture failed:\n" + msg, "danger");
        },
    });
}

/* ---- Live View (MJPEG stream) ---- */
function toggleLiveLoop() {
    if (liveLoopActive) { stopLive(); } else { startLive(); }
}

function refreshStreamSrc() {
    // Use AllskyPlayer if available (WebSocket + canvas player)
    if (typeof player !== "undefined" && player !== null) {
        var playerEl = document.getElementById("allsky-player-container");
        var staticImg = document.getElementById("latest-image");
        if (playerEl) playerEl.style.display = "";
        if (staticImg) staticImg.style.display = "none";
        player.connect();
        return;
    }
    // Fallback: plain MJPEG <img>
    var streamUrl = "/indi-allsky/api/stream/feed.mjpeg?t=" + Date.now();
    var target = document.getElementById("latest-image") || document.getElementById("loop-image");
    if (target) {
        target.onerror = function() {
            if (liveLoopActive) {
                showToast("MJPEG stream disconnected. The stream may have died.\nTry clicking Live View again.", "warning");
                $("#live-status").text("Stream disconnected");
            }
        };
        target.src = streamUrl;
    }
}

function startLive(retryCount) {
    retryCount = retryCount || 0;
    $("#btn-live-loop").text("Starting...").prop("disabled", true);
    $("#live-status").text(retryCount > 0 ? "Retrying (" + retryCount + ")..." : "Stopping allsky, starting stream...");
    var params = getLiveParams();
    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/start?" + params, timeout: 30000,
        success: function(rdata) {
            liveLoopActive = true;
            $("#btn-live-loop").text("Stop Live").removeClass("btn-outline-success").addClass("btn-success").prop("disabled", false);
            var mode = (typeof player !== "undefined" && player !== null) ? "WebSocket" : "MJPEG";
            $("#live-status").text("Live - " + mode + " stream");
            refreshStreamSrc();
        },
        error: function(xhr) {
            var msg = xhr.responseJSON ? xhr.responseJSON.error : "Failed to start stream (HTTP " + xhr.status + ")";
            if (retryCount < 2) {
                $("#live-status").text("Failed, retrying in 2s...");
                showToast("Stream start failed (attempt " + (retryCount + 1) + "/3):\n" + msg + "\n\nRetrying...", "warning");
                setTimeout(function() { startLive(retryCount + 1); }, 2000);
            } else {
                $("#btn-live-loop").text("Live View").prop("disabled", false);
                $("#live-status").text("Failed to start stream");
                showToast("Stream failed after 3 attempts:\n" + msg, "danger");
            }
        },
    });
}

function stopLive() {
    liveLoopActive = false;
    $("#btn-live-loop").text("Stopping...").prop("disabled", true);
    // Disconnect player and show static image
    if (typeof player !== "undefined" && player !== null) {
        player.disconnect();
        var playerEl = document.getElementById("allsky-player-container");
        var staticImg = document.getElementById("latest-image");
        if (playerEl) playerEl.style.display = "none";
        if (staticImg) staticImg.style.display = "";
    } else {
        var target = document.getElementById("latest-image") || document.getElementById("loop-image");
        if (target) target.src = "";
    }
    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/stop", timeout: 20000,
        success: function() {
            $("#btn-live-loop").text("Live View").removeClass("btn-success").addClass("btn-outline-success").prop("disabled", false);
            $("#live-status").text("Allsky restarting...");
            setTimeout(function() { $("#live-status").text(""); }, 5000);
        },
        error: function() {
            $("#btn-live-loop").text("Live View").removeClass("btn-success").addClass("btn-outline-success").prop("disabled", false);
            $("#live-status").text("");
        },
    });
}

/* ---- Auto-detect sensor and adjust gain ranges ---- */
function detectSensor() {
    $.ajax({
        type: "GET", url: "/indi-allsky/api/sensor_info", timeout: 10000,
        success: function(data) {
            var gainMax = data.gain_max || 16.0;
            var gainMin = data.gain_min || 0;
            var label = data.label || data.sensor || "Camera";
            // Update config section header
            var hdr = document.querySelector("#slider-panel .text-info");
            if (hdr) hdr.textContent = label + " Settings";
            // Update gain slider ranges
            ["NIGHT_GAIN", "MOONMODE_GAIN", "DAY_GAIN", "live_gain"].forEach(function(id) {
                var el = document.getElementById("slider-" + id);
                if (el) {
                    el.min = gainMin;
                    el.max = gainMax;
                    // Update the def in sliderDefs too
                    var def = sliderDefs.find(function(s) { return s.id === id; });
                    if (def) { def.min = gainMin; def.max = gainMax; }
                }
            });
        },
    });
}

/* ---- Init ---- */
$(document).ready(function() {
    buildSliderPanel();
    detectSensor();
    loadConfig();
    // Check if stream is already running (e.g. another tab started it)
    $.ajax({
        type: "GET", url: "/indi-allsky/api/stream/status", timeout: 5000,
        success: function(data) {
            if (data.running) {
                liveLoopActive = true;
                $("#btn-live-loop").text("Stop Live").removeClass("btn-outline-success").addClass("btn-success");
                var mode = (typeof player !== "undefined" && player !== null) ? "WebSocket" : "MJPEG";
                $("#live-status").text("Live - " + mode + " stream (" + (data.clients || 0) + " viewers)");
                refreshStreamSrc();
            }
        },
    });
});
