# Keograms

A keogram compresses an entire night of sky conditions into a single composite image. It is constructed by extracting a vertical strip of pixels along the central meridian from each sequential capture frame and appending them chronologically from left (sunset/dusk) to right (sunrise/dawn).

The horizontal axis represents time; the vertical axis represents the sky from horizon to zenith to opposing horizon. Keograms provide an immediate diagnostic summary of cloud cover, auroral activity, light pollution shifts, and clear-sky intervals across the night.

---

## 1. Meridian Alignment & Rotation

For celestial and meteorological features to track consistently, the vertical slice must align with the local celestial meridian (the North-South celestial circle passing through the zenith).

> [!NOTE]
> Keogram rotation angles, vertical/horizontal scaling, and realtime keogram generation parameters under **Configuration** → **Processing** are hidden by default in Simple Mode. Enable **Expert Mode** using the toggle switch in the top configuration header.

In **Configuration** → **Processing** → **Keogram**:

* `KEOGRAM_ROTATION`: Rotates the source frame before extracting the central pixel column.
  * `0`: No rotation applied.
  * Positive values (`1` to `180`): Rotates the image counter-clockwise (CCW).
  * Negative values (`-1` to `-180`): Rotates the image clockwise (CW).

### Determining the Rotation Angle
1. Identify true North and South in a calibrated night image (e.g. using Polaris in the northern hemisphere or Crux in the southern hemisphere, or reference the [VirtualSky](VirtualSky) overlay).
2. Measure the angular deviation between your camera sensor vertical axis and the true North-South meridian line.
3. Apply the corresponding degree adjustment to `KEOGRAM_ROTATION` so North appears at the top and South at the bottom of the extracted column.

---

## 2. Generation Modes

### Automatic Nightly Compilation
The background capture daemon compiles the final nightly keogram automatically at dawn once the Sun rises above the configured daylight horizon threshold. Assets are recorded in `IndiAllSkyDbKeogramTable` and stored in `/var/www/html/allsky/images/`.

### Realtime Incremental Keograms
`indi-allsky` can generate an incremental keogram that updates dynamically after every individual capture throughout the night:
* Enable **Configuration** → **Image Processing** → **Realtime Keogram** (`REALTIME_KEOGRAM__ENABLE`).
* View the live progress in the web interface at:
  ```
  https://<allsky-host>/indi-allsky/realtime_keogram
  ```

### Historical Keogram Regeneration
If a historical date requires regeneration:
1. Open the web interface and navigate to **Images** for the target date (`https://<allsky-host>/indi-allsky/images?dayDate=YYYYMMDD`).
2. Select **Actions** → **Generate Video/Keogram/Star Trails**.
3. The web application dispatches a `generateKeogramStarTrails` task into the daemon's internal `VIDEO` task queue (`TaskQueueQueue.VIDEO`). The capture daemon processes the task asynchronously in the background.

---

## 3. Related Documentation

* [Long-Term Keograms](Long-Term-Keogram) — Compiling multi-night and year-long keograms.
* [Detection Masks](Detection-Masks) — Excluding horizon obstructions from processing.
