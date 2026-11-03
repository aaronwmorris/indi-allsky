# Star Detection Engines

`indi-allsky` tracks celestial clarity and transparency by counting detected stars across captured nighttime frames. The star count is logged in the database (`IndiAllSkyDbImageTable`), rendered as image overlay text, and plotted on telemetry graphs.

The detection method is configured under **Configuration** → **Processing** in the **Star & Meteor Detection Engine** section.

> [!NOTE]
> The **Star & Meteor Detection Engine** settings card is hidden by default in Simple Mode. Enable **Expert Mode** using the toggle switch in the top configuration header to access star detection thresholds.

---

## 1. Detection Algorithms

### A. SEP (Source Extractor in Python) — Recommended
`SEP` calculates a dynamic, two-dimensional model of the sky background and RMS noise across the frame, subtracts the background, and identifies stellar sources exceeding a statistical significance threshold.
* **Advantages**: Normalized against shifting background illumination (such as twilight, urban light pollution, and moon phases). Star counts remain mathematically comparable over time.
* **Lens Distortion Resilient**: Accurately detects elongated or distorted stars near the peripheral edges of wide fisheye lenses.

### B. Template Matching (OpenCV)
Template matching cross-correlates image features against a fixed circular star kernel.
* **Limitations**: Highly sensitive to sky brightness shifts. Because fisheye lenses produce significant radial optical distortion (coma, astigmatism) near the horizon, stars outside the central sensor area are frequently missed.
* Retained for legacy installations or low-power embedded processors where background modeling overhead must be minimized.

---

## 2. Configuration Reference (SEP Engine)

| Parameter | Type | Default | Recommended Range | Description |
|---|---|---|---|---|
| `DETECT_STARS_METHOD` | Select | `sep` | `sep` / `template` | Active star detection algorithm. |
| `DETECT_STARS_SEP_THOLD` | Float | `5.0` | `3.0` – `15.0` | Significance threshold (in standard deviations $\sigma$ above the local background RMS noise). Lower values detect fainter stars but increase susceptibility to noise artifacts. |
| `DETECT_STARS_SEP_MAX_RADIUS` | Integer | `20` | `5` – `30` | Maximum allowable object radius (in pixels). Excludes large saturated star blooms, satellites, or illuminated cloud edges from inflating star counts. |

### Calibrating Sigma Thresholds (`DETECT_STARS_SEP_THOLD`)
* **`3.0`**: Faint limiting magnitude; captures marginal stars but may count high-gain noise spikes.
* **`5.0` (Default)**: Balanced for typical suburban/rural skies.
* **`10.0` – `15.0`**: Restricts detection strictly to prominent navigational stars (useful in light-polluted urban environments).

---

## 3. Interactive Detection Tuning

Before committing detection parameters:
1. Establish an accurate [Detection Mask](Detection-Masks) to exclude trees, buildings, and ground illumination.
2. In the web interface, open **Configuration** → **Image Processing** → **Detection Tuning**.
3. Toggle **Run Detection** and select **Process**.
4. The preview image renders detected stars (with centroid bounding boxes) and reports total counts. Adjust thresholds interactively until counts accurately reflect genuine stars.
