# Redirect Views and Integration Endpoints

`indi-allsky` exposes HTTP redirect endpoints that issue `302 Found` responses resolving dynamically to the latest captured or generated media files. These routes facilitate external integrations, digital signage, round display widgets, Home Assistant dashboards, and public website embeds.

> [!NOTE]
> If `INDI_ALLSKY_AUTH_MEDIA_VIEWS` is enabled in `/etc/indi-allsky/flask.json`, redirect requests originating from unauthenticated sessions or clients outside `ADMIN_NETWORKS` will be rejected with `401 Unauthorized` or redirected to the login interface.

---

## 1. Direct Media Asset Redirects

These routes redirect directly to the raw static binary file (JPEG, PNG, MP4, DNG):

| Endpoint | Target Media | Query Parameters |
|---|---|---|
| `/indi-allsky/latestimage` | Latest processed primary sky image | `camera_id` (int) |
| `/indi-allsky/latestthumbnail` | Latest image thumbnail | `camera_id` (int) |
| `/indi-allsky/latestkeogram` | Latest daily or realtime keogram | `camera_id` (int), `night` (0 or 1) |
| `/indi-allsky/lateststartrail` | Latest composite star trail image | `camera_id` (int) |
| `/indi-allsky/latestpanorama` | Latest unwarped panoramic image | `camera_id` (int) |
| `/indi-allsky/latestraw` | Latest raw camera frame (DNG/FITS) | `camera_id` (int) |
| `/indi-allsky/latesttimelapse` | Latest compiled daily timelapse video | `camera_id` (int), `night` (0 or 1) |
| `/indi-allsky/lateststartrailvideo` | Latest star trail accumulation video | `camera_id` (int) |
| `/indi-allsky/latestpanoramavideo` | Latest panoramic timelapse video | `camera_id` (int), `night` (0 or 1) |

### Query Parameter Descriptions
* **`camera_id`**: Numerical identifier of the camera profile (`SELECT id FROM camera;`). If omitted, defaults to the lowest active camera ID.
* **`night`**: Binary selector for day vs. night compilations:
  * `night=1`: Nighttime compilation (default).
  * `night=0`: Daytime compilation.

### Direct Download Example
```bash
# Fetch latest full-resolution sky frame follow redirects (-L)
curl -L -s -o "latest_$(date +%Y%m%d_%H%M%S).jpg" https://allsky.local/indi-allsky/latestimage

# Fetch latest daytime timelapse video for camera ID 2
curl -L -s -o "daytime_timelapse.mp4" "https://allsky.local/indi-allsky/latesttimelapse?camera_id=2&night=0"
```

---

## 2. Templated HTML View Redirects

These routes redirect to the full responsive web application viewer displaying the corresponding asset with metadata and controls:

| Endpoint | Target HTML Viewer | Query Parameters |
|---|---|---|
| `/indi-allsky/latestimageview` | Single-image inspection viewer | `camera_id` (int) |
| `/indi-allsky/latestkeogramview` | Keogram inspection viewer | `camera_id` (int), `night` (0 or 1) |
| `/indi-allsky/lateststartrailview` | Star trail inspection viewer | `camera_id` (int) |
| `/indi-allsky/latestpanoramaview` | Panoramic image viewer | `camera_id` (int) |
| `/indi-allsky/latestrawview` | RAW frame inspection viewer | `camera_id` (int) |
| `/indi-allsky/latesttimelapsewatch` | Video player for daily timelapse | `camera_id` (int), `night` (0 or 1) |
| `/indi-allsky/lateststartrailvideowatch`| Video player for star trail timelapse | `camera_id` (int) |
| `/indi-allsky/latestpanoramavideowatch`| Video player for panoramic timelapse | `camera_id` (int), `night` (0 or 1) |

---

## 3. Dedicated Live View Shortcuts

For embedded displays (e.g. tablet kiosks or circular gauge displays), specialized index aliases provide immediate live rendering:

* `/indi-allsky/panorama` — Live panoramic image view (`index_img.html`).
* `/indi-allsky/panorama_canvas` — Live panoramic HTML5 canvas view (`index_canvas.html`).
* `/indi-allsky/raw` — Live raw image view (`index_img.html`).
* `/indi-allsky/raw_canvas` — Live raw HTML5 canvas view (`index_canvas.html`).
* `/indi-allsky/js/latest` — Lightweight JSON payload describing the latest captured frame metadata.


