# Sun and Moon Perimeter Orbs

The orb overlay subsystem calculates high-precision ephemeris positions for the Sun and Moon using the `ephem` library, projecting their positions along the perimeter border of captured images. This provides immediate visual context regarding diurnal cycles, moon phase illumination, and twilight transitions.

---

## 1. Projection Modes

The orb calculation mode is configured under **Camera Settings -> Overlay -> Orb Properties** (`ORB_PROPERTIES -> MODE`):

| Mode | Key | Description |
|---|---|---|
| **Local Hour Angle** | `ha` | Simulates a 24-hour diurnal clock along the rectangular image perimeter. Top-center (12:00) represents upper meridian transit (solar noon). |
| **Azimuth** | `az` | Projects coordinates using 360° compass bearings. By default, 0° (North) aligns with the top-center edge. |
| **Altitude** | `alt` | Projects coordinates vertically along the image margins (+90° to -90°). Ascending bodies appear on the right margin; descending bodies appear on the left margin. |
| **Disabled** | `off` | Deactivates orb calculations and perimeter renderings. |

---

## 2. Twilight and Altitude Boundary Indicators

When `ha` or `az` mode is active, indicator tick marks are plotted along the image edge to mark key solar altitude thresholds:

- **0.0°** — Astronomical Horizon (Sunrise / Sunset)
- **-6.0°** — Civil Dawn / Dusk
- **-12.0°** — Nautical Dawn / Dusk
- **-18.0°** — Astronomical Dawn / Dusk

The larger, accented tick mark (rendered in the primary text color) indicates the configured **Night Sun Altitude** (`NIGHT_SUN_ALTITUDE`, typically -6°). This boundary marks the exact threshold where `indi-allsky` transitions between daytime auto-exposure routines and nighttime long-exposure sequences.

---

## 3. Configuration Parameters

> [!NOTE]
> The **Orb Properties** settings card under **Configuration** → **Overlays** is hidden by default in Simple Mode. Enable **Expert Mode** via the toggle switch in the top configuration header to access orb settings.

In the web interface under **Configuration -> Overlays -> Orb Properties**, or via JSON configuration:

```json
"ORB_PROPERTIES": {
    "MODE": "ha",
    "RADIUS": 9,
    "SUN_COLOR": [200, 200, 0],
    "MOON_COLOR": [128, 128, 128],
    "AZ_OFFSET": 0.0,
    "RETROGRADE": false
}
```

* **`MODE`**: Selects `ha` (Hour Angle), `az` (Azimuth), `alt` (Altitude), or `off`.
* **`RADIUS`**: Integer pixel radius for the rendered celestial circles (default: `9`).
* **`SUN_COLOR`**: RGB array defining the rendered solar marker color (default: `[200, 200, 0]`, yellow).
* **`MOON_COLOR`**: RGB array defining the rendered lunar marker color (default: `[128, 128, 128]`, neutral grey).
* **`AZ_OFFSET`**: Float value in degrees to compensate for physical camera rotational misalignment relative to true North. Valid for `ha` and `az` modes.
* **`RETROGRADE`**: Boolean flag (`true` / `false`). When optical paths incorporate mirrored surfaces or software image inversions (flip horizontal/vertical), set to `true` to invert orb travel along the perimeter.

