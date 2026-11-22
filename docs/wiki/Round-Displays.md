# Circular & Round Display Output

`indi-allsky` provides integrated support for circular LCD/AMOLED displays and microcontroller-based viewers (e.g., ESP32 round disc displays, Waveshare 1.28-inch GC9A01 panels, ST7789 circular screens, and circular HDMI monitors).

---

## 1. Output Generation

When circular display generation is enabled, the image processing pipeline:
1. Calculates optical center alignment using `LENS_OFFSET_X` and `LENS_OFFSET_Y`.
2. Crops the frame to `IMAGE_CIRCLE_DIAMETER` centered on the optical axis.
3. Pads non-circular sensor margins with black borders (`[0, 0, 0]` BGR).
4. Rescales the resulting square frame to the configured `RESOLUTION` (800x800, 720x720, or 1080x1080).
5. Writes the file to the web root at `circular_display.<ext>` (e.g. `/var/www/html/allsky/images/circular_display.jpg`).

---

## 2. Configuration Reference

Settings are configured in the web interface under **Configuration** → **Image Processing** → **Circular Display**:

| Parameter | Type | Options / Range | Default | Description |
|---|---|---|---|---|
| `ENABLE` | Boolean | `true` / `false` | `false` | Enables generation of `circular_display.jpg` on every image capture cycle. |
| `RESOLUTION` | Select | `800` (800x800)<br>`720` (720x720)<br>`1080` (1080x1080) | `800` | Native square dimension for the primary generated output image. |
| `IMAGE_CIRCLE_DIAMETER` | Integer | $\ge 100$ pixels | `3500` | Diameter in unbinned sensor pixels of the fisheye lens circle. |

Optical centering is shared with the primary lens geometry settings:
* `LENS_OFFSET_X`: Horizontal pixel offset of the optical axis relative to the sensor center.
* `LENS_OFFSET_Y`: Vertical pixel offset of the optical axis relative to the sensor center.

---

## 3. Dedicated ESP32 Endpoint (`/allsky_esp32`)

For embedded microcontroller viewers (such as ESP32 Wi-Fi round disc desk clocks and status monitors), `indi-allsky` provides an unauthenticated, bandwidth-efficient streaming endpoint:

```
GET /indi-allsky/allsky_esp32?size=<SIZE>&camera_id=<CAMERA_ID>
```

### Query Parameters
* `size`: Target square resolution. Valid choices are restricted to **`240`**, **`280`**, **`320`**, **`720`**, or **`800`** (defaults to `240` if omitted or invalid).
* `camera_id`: (Optional) ID of the target camera. Defaults to `0` (the active or most recently captured camera).

### Behavior
* If `CIRCULAR_DISPLAY.ENABLE` is active and `circular_display.jpg` exists, the endpoint reads and scales the cropped circular image.
* If circular display output is disabled, the endpoint falls back to resizing the latest raw capture frame.
* The response is encoded in JPEG format using the configured `IMAGE_FILE_COMPRESSION` quality and served directly with `Content-Type: image/jpeg`.