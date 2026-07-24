## Sub-task breakdown

**Root cause hypothesis:** There is no dedicated, unauthenticated endpoint that serves the latest allsky image pre-resized to a square JPEG for ESP32 round-display firmware, which requires a direct (non-redirect) URL with no auth and JPEG-only output at 720×720 or 800×800.

**Files to change:**
- `indi_allsky/config.py`: Add a new `ESP32VIEWER` config block (enabled flag, image size, jpeg quality) to `IndiAllSkyConfigBase._base_config` defaults.
- `indi_allsky/flask/views.py`: Add a new `Esp32LatestImageView` class that reads the latest image from the filesystem, resizes it to the configured square size with OpenCV, encodes as JPEG, and returns a direct `Response` — with no auth decorator. Register the URL rule at the bottom of the file.
- `indi_allsky/flask/forms.py`: Add UI form fields for the new `ESP32VIEWER` config block so the settings page exposes the options.

**Sub-tasks:**
1. [ ] Add `ESP32VIEWER` config defaults to `IndiAllSkyConfigBase._base_config` in `indi_allsky/config.py` — done when the dict contains `ENABLE` (bool, default False), `IMAGE_SIZE` (int, default 720), and `JPEG_QUALITY` (int, default 90), and existing config validation/migration handles the new keys.
2. [ ] Implement `Esp32LatestImageView` in `indi_allsky/flask/views.py` — done when a `GET /esp32viewer` request returns a direct `image/jpeg` `Response` (no redirect, no auth check) with the latest image resized to a square matching `ESP32VIEWER.IMAGE_SIZE`, using OpenCV for resizing and JPEG encoding; returns 503 when no image is available, and 404 when the feature is disabled.
3. [ ] Register the URL rule `bp_allsky.add_url_rule('/esp32viewer', ...)` near the bottom of `indi_allsky/flask/views.py` — done when the route is reachable without a login session.
4. [ ] Add form fields for `ESP32VIEWER` (enable toggle, size selector for 720/800, quality slider) to `IndiAllskyConfigForm` in `indi_allsky/flask/forms.py` and wire them to the existing config save/load logic — done when saving via the UI persists the values and the page renders without error.

**Risks / unknowns:**
- The latest image path is resolved via the filesystem symlink `images/latest.<ext>` (e.g. `latest.jpg`, `latest.webp`). The extension varies by `IMAGE_FILE_TYPE` config and may be WebP; the new view must handle reading any supported source format (WebP via cv2, JPEG via simplejpeg or cv2, PNG via cv2) before re-encoding as JPEG.
- OpenCV's `imread` does not support WebP on all platforms; need to verify or fall back to Pillow for WebP source images.
- The `images/` path is typically served by nginx directly, not Flask; the new endpoint must be a Flask route under the app's URL space so auth middleware is bypassed cleanly, not a static file served by nginx (which would require nginx config changes).
- No nginx/Apache config change should be required — the endpoint must work through the Flask app alone, consistent with how `Fits2JpegView` works.
- The `camera_id` parameter used by most views to select the right camera needs a sensible default for the ESP32 endpoint (e.g., first/primary camera) since the firmware has no way to pass a camera selector.
- Need to confirm whether the `INDI_ALLSKY_AUTH_ALL_VIEWS` setting would inadvertently apply a global auth middleware that wraps all routes, which would block the ESP32 firmware even without a per-view decorator.
