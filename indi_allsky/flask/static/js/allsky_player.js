/**
 * AllskyPlayer - Live stream player with WebSocket + MJPEG fallback.
 *
 * WebSocket mode: binary frames with metadata header, rendered to <canvas>.
 * MJPEG fallback: <img src="feed.mjpeg"> when WebSocket not available.
 *
 * Usage:
 *   var player = new AllskyPlayer({
 *     container: document.getElementById('player-container'),
 *     wsUrl: '/indi-allsky/api/stream/ws',
 *     feedUrl: '/indi-allsky/api/stream/feed.mjpeg',
 *     metadataUrl: '/indi-allsky/api/stream/metadata',
 *   });
 *   player.connect();
 *   player.disconnect();
 */

(function (window) {
  "use strict";

  function AllskyPlayer(opts) {
    this.container = opts.container;
    this.wsUrl = opts.wsUrl || "/indi-allsky/api/stream/ws";
    this.feedUrl = opts.feedUrl || "/indi-allsky/api/stream/feed.mjpeg";
    this.metadataUrl = opts.metadataUrl || "/indi-allsky/api/stream/metadata";
    this.preferWs = opts.preferWs !== false; // default: try WebSocket first
    this.onstatuschange = opts.onstatuschange || function () {};
    this.onmetadata = opts.onmetadata || function () {};

    this._connected = false;
    this._expanded = false;
    this._useWs = false; // true when WebSocket is active
    this._ws = null;
    this._reconnectTimer = null;
    this._metaPollTimer = null;
    this._metadata = null;
    this._naturalWidth = 0;
    this._naturalHeight = 0;

    this._build();
    this._bindEvents();
  }

  AllskyPlayer.prototype._build = function () {
    var c = this.container;
    c.classList.add("allsky-player");
    c.innerHTML = "";

    // Inline view wrapper
    var inline = document.createElement("div");
    inline.className = "allsky-player__inline";
    c.appendChild(inline);
    this._inlineWrap = inline;

    // Canvas for WebSocket mode
    var canvas = document.createElement("canvas");
    canvas.className = "allsky-player__canvas";
    canvas.style.display = "none";
    inline.appendChild(canvas);
    this._canvas = canvas;

    // Image element for MJPEG fallback
    var img = document.createElement("img");
    img.className = "allsky-player__img";
    img.alt = "Live stream";
    img.style.display = "none";
    inline.appendChild(img);
    this._img = img;

    // Offline overlay
    var offline = document.createElement("div");
    offline.className = "allsky-player__offline";
    offline.innerHTML =
      '<p class="allsky-player__offline-title">Stream offline</p>' +
      '<p class="allsky-player__offline-sub">Click Live View to start</p>';
    inline.appendChild(offline);
    this._offline = offline;

    // Info bar (bottom)
    var infoBar = document.createElement("div");
    infoBar.className = "allsky-player__info-bar";
    infoBar.innerHTML =
      '<span class="allsky-player__info-left"></span>' +
      '<span class="allsky-player__info-right"></span>';
    inline.appendChild(infoBar);
    this._infoBar = infoBar;
    this._infoLeft = infoBar.querySelector(".allsky-player__info-left");
    this._infoRight = infoBar.querySelector(".allsky-player__info-right");

    // Hover buttons (expand + fullscreen)
    var btns = document.createElement("div");
    btns.className = "allsky-player__hover-btns";
    btns.innerHTML =
      '<button class="allsky-player__btn" data-action="expand" title="Expand (or double-click)">' +
      '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 3h6m0 0v6m0-6l-7 7M9 21H3m0 0v-6m0 6l7-7"/></svg>' +
      "</button>" +
      '<button class="allsky-player__btn" data-action="fullscreen" title="Fullscreen">' +
      '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5"/></svg>' +
      "</button>";
    inline.appendChild(btns);
    this._hoverBtns = btns;

    // Modal overlay (hidden by default)
    var modal = document.createElement("div");
    modal.className = "allsky-player__modal";
    modal.style.display = "none";
    modal.innerHTML =
      '<div class="allsky-player__modal-inner">' +
      '<div class="allsky-player__modal-controls">' +
      '<span class="allsky-player__modal-info"></span>' +
      '<button class="allsky-player__btn" data-action="modal-fullscreen" title="Fullscreen">' +
      '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5"/></svg>' +
      "</button>" +
      '<button class="allsky-player__btn" data-action="close" title="Close (Esc)">' +
      '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>' +
      "</button>" +
      "</div>" +
      '<canvas class="allsky-player__modal-canvas" style="display:none"></canvas>' +
      '<img class="allsky-player__modal-img" alt="Live stream expanded" style="display:none">' +
      "</div>";
    document.body.appendChild(modal);
    this._modal = modal;
    this._modalInner = modal.querySelector(".allsky-player__modal-inner");
    this._modalCanvas = modal.querySelector(".allsky-player__modal-canvas");
    this._modalImg = modal.querySelector(".allsky-player__modal-img");
    this._modalInfo = modal.querySelector(".allsky-player__modal-info");
  };

  AllskyPlayer.prototype._bindEvents = function () {
    var self = this;

    // Double-click to expand
    this._canvas.addEventListener("dblclick", function () {
      self.expand();
    });
    this._img.addEventListener("dblclick", function () {
      self.expand();
    });

    // Hover button actions
    this._hoverBtns.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-action]");
      if (!btn) return;
      var action = btn.dataset.action;
      if (action === "expand") self.expand();
      else if (action === "fullscreen") {
        self.expand();
        setTimeout(function () {
          self._goFullscreen(self._modalInner);
        }, 100);
      }
    });

    // Modal actions
    this._modal.addEventListener("click", function (e) {
      if (e.target === self._modal) self.collapse();
      var btn = e.target.closest("[data-action]");
      if (!btn) return;
      var action = btn.dataset.action;
      if (action === "close") self.collapse();
      else if (action === "modal-fullscreen")
        self._goFullscreen(self._modalInner);
    });

    // Escape to close
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && self._expanded) self.collapse();
    });

    // MJPEG img events
    this._img.addEventListener("error", function () {
      if (self._connected && !self._useWs) {
        self._connected = false;
        self._showOffline(true);
        self.onstatuschange(false);
      }
    });
    this._img.addEventListener("load", function () {
      if (!self._connected && !self._useWs) {
        self._connected = true;
        self._showOffline(false);
        self.onstatuschange(true);
      }
    });
  };

  // ---- Connection ----

  AllskyPlayer.prototype.connect = function () {
    if (this.preferWs) {
      this._connectWs();
    } else {
      this._connectMjpeg();
    }
  };

  AllskyPlayer.prototype.disconnect = function () {
    this._disconnectWs();
    this._disconnectMjpeg();
    this._stopMetaPoll();
    this._connected = false;
    this._showOffline(true);
    this.onstatuschange(false);
    if (this._expanded) this.collapse();
  };

  AllskyPlayer.prototype.reconnect = function () {
    this.disconnect();
    this.connect();
  };

  // ---- WebSocket mode ----

  AllskyPlayer.prototype._connectWs = function () {
    var self = this;
    if (this._ws && (this._ws.readyState === 0 || this._ws.readyState === 1))
      return;

    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + this.wsUrl;

    var ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this._ws = ws;

    ws.onopen = function () {
      console.log("[AllskyPlayer] WS connected to", url);
      self._useWs = true;
      self._connected = true;
      self._canvas.style.display = "";
      self._img.style.display = "none";
      self._showOffline(false);
      self.onstatuschange(true);
    };

    ws.onclose = function (ev) {
      console.log("[AllskyPlayer] WS closed:", ev.code, ev.reason);
      self._connected = false;
      self.onstatuschange(false);
      self._scheduleReconnect();
    };

    ws.onerror = function (ev) {
      console.error("[AllskyPlayer] WS error:", ev);
      if (!self._connected) {
        self._useWs = false;
        self._connectMjpeg();
        return;
      }
      self._connected = false;
      self.onstatuschange(false);
    };

    ws.onmessage = function (event) {
      if (!(event.data instanceof ArrayBuffer) || event.data.byteLength < 4) {
        console.log("[AllskyPlayer] WS msg: not arraybuffer or too small, type=", typeof event.data, "len=", event.data ? event.data.byteLength || event.data.length : 0);
        return;
      }
      self._frameCounter = (self._frameCounter || 0) + 1;
      console.log("[AllskyPlayer] Frame", self._frameCounter, ":", event.data.byteLength, "bytes");

      var view = new DataView(event.data);
      var jsonLen = view.getUint32(0);

      // Parse metadata
      if (jsonLen > 0 && jsonLen < event.data.byteLength) {
        try {
          var jsonBytes = new Uint8Array(event.data, 4, jsonLen);
          var meta = JSON.parse(new TextDecoder().decode(jsonBytes));
          self._metadata = meta;
          self._updateInfoBar(meta);
          self.onmetadata(meta);
        } catch (e) {}
      }

      // JPEG data
      var jpegOffset = 4 + jsonLen;
      var jpegData = new Uint8Array(event.data, jpegOffset);
      if (jpegData.byteLength < 2) return;

      var blob = new Blob([jpegData], { type: "image/jpeg" });
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () {
        self._naturalWidth = img.naturalWidth;
        self._naturalHeight = img.naturalHeight;

        // Draw to inline canvas
        if (self._canvas) {
          self._canvas.width = img.naturalWidth;
          self._canvas.height = img.naturalHeight;
          var ctx = self._canvas.getContext("2d");
          ctx.drawImage(img, 0, 0);
        }

        // Draw to modal canvas if expanded
        if (self._expanded && self._modalCanvas) {
          self._modalCanvas.width = img.naturalWidth;
          self._modalCanvas.height = img.naturalHeight;
          var ctx2 = self._modalCanvas.getContext("2d");
          ctx2.drawImage(img, 0, 0);
        }

        URL.revokeObjectURL(url);
      };
      img.src = url;
    };
  };

  AllskyPlayer.prototype._disconnectWs = function () {
    if (this._ws) {
      this._ws.onclose = null;
      this._ws.onerror = null;
      this._ws.close();
      this._ws = null;
    }
    this._useWs = false;
    this._canvas.style.display = "none";
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
  };

  AllskyPlayer.prototype._scheduleReconnect = function () {
    var self = this;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._reconnectTimer = setTimeout(function () {
      self._connectWs();
    }, 3000);
  };

  // ---- MJPEG fallback mode ----

  AllskyPlayer.prototype._connectMjpeg = function () {
    this._useWs = false;
    this._canvas.style.display = "none";
    this._img.style.display = "";
    this._img.src = this.feedUrl + "?t=" + Date.now();
    this._showOffline(false);
    this._startMetaPoll();
  };

  AllskyPlayer.prototype._disconnectMjpeg = function () {
    this._img.src = "";
    this._img.style.display = "none";
  };

  // ---- Expand / Fullscreen ----

  AllskyPlayer.prototype.expand = function () {
    this._expanded = true;
    this._modal.style.display = "";
    if (this._useWs) {
      this._modalCanvas.style.display = "";
      this._modalImg.style.display = "none";
    } else {
      this._modalCanvas.style.display = "none";
      this._modalImg.style.display = "";
      this._modalImg.src = this.feedUrl + "?t=" + Date.now();
    }
  };

  AllskyPlayer.prototype.collapse = function () {
    this._expanded = false;
    this._modal.style.display = "none";
    this._modalImg.src = "";
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function () {});
    }
  };

  AllskyPlayer.prototype._goFullscreen = function (el) {
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function () {});
    } else {
      el.requestFullscreen().catch(function () {});
    }
  };

  AllskyPlayer.prototype._showOffline = function (show) {
    this._offline.style.display = show ? "" : "none";
    this._infoBar.style.display = show ? "none" : "";
  };

  // ---- Metadata polling (MJPEG mode only) ----

  AllskyPlayer.prototype._startMetaPoll = function () {
    var self = this;
    this._stopMetaPoll();
    this._pollMeta();
    this._metaPollTimer = setInterval(function () {
      self._pollMeta();
    }, 1500);
  };

  AllskyPlayer.prototype._stopMetaPoll = function () {
    if (this._metaPollTimer) {
      clearInterval(this._metaPollTimer);
      this._metaPollTimer = null;
    }
  };

  AllskyPlayer.prototype._pollMeta = function () {
    var self = this;
    var xhr = new XMLHttpRequest();
    xhr.open("GET", this.metadataUrl, true);
    xhr.timeout = 3000;
    xhr.onload = function () {
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          self._metadata = data;
          self._updateInfoBar(data);
          self.onmetadata(data);
        } catch (e) {}
      }
    };
    xhr.send();
  };

  AllskyPlayer.prototype._updateInfoBar = function (meta) {
    console.log("[AllskyPlayer] OSD meta:", JSON.stringify(meta));
    var left = "";
    var right = "";

    // Left side: exposure, gain, lux
    if (meta.exposure != null) {
      left += _formatExp(meta.exposure);
    }
    if (meta.gain != null) {
      left += (left ? " \u00b7 " : "") + "gain " + meta.gain.toFixed(1);
    }
    if (meta.lux != null && meta.lux > 0) {
      left += (left ? " \u00b7 " : "") + meta.lux.toFixed(0) + " lux";
    }

    // Right side: sensor temp, colour temp, fps, frames
    if (meta.sensor_temp != null) {
      right += parseFloat(meta.sensor_temp).toFixed(1) + "\u00b0C";
    }
    if (meta.colour_temp != null && meta.colour_temp > 0) {
      right += (right ? " \u00b7 " : "") + meta.colour_temp + "K";
    }
    // Stream stats (from polling endpoint or WebSocket meta)
    var s = meta._stream || meta;
    if (s.fps != null) {
      right += (right ? " \u00b7 " : "") + s.fps + " fps";
    }
    if (s.frame != null || s.frames != null) {
      right += " \u00b7 #" + (s.frame || s.frames || 0);
    }

    this._infoLeft.textContent = left || "--";
    this._infoRight.textContent = right || "--";

    // Also update modal info
    if (this._expanded && this._modalInfo) {
      this._modalInfo.textContent =
        left + (left && right ? "  |  " : "") + right;
    }
  };

  // ---- Helpers ----

  function _formatExp(v) {
    if (v == null) return "--";
    if (v < 0.001) return (v * 1000000).toFixed(0) + "\u00b5s";
    if (v < 1) return (v * 1000).toFixed(1) + "ms";
    return v.toFixed(2) + "s";
  }

  AllskyPlayer.prototype.destroy = function () {
    this.disconnect();
    if (this._modal && this._modal.parentNode) {
      this._modal.parentNode.removeChild(this._modal);
    }
  };

  window.AllskyPlayer = AllskyPlayer;
})(window);
