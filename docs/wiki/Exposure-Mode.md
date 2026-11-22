# Exposure Modes & Auto-Gain

The Exposure Mode subsystem controls how `indi-allsky` regulates sensor exposure duration and analog/digital gain across varying daylight and nocturnal sky conditions.

Configuration parameters are located in the web interface under **Configuration** → **Exposure**.

---

## 1. Operating Modes

### A. Basic Mode
In Basic mode, camera gain remains fixed at static preset values for each discrete astronomical solar/lunar state, with image brightness regulated strictly by adjusting exposure duration:
* **Day Mode**: Sun altitude $> -6.0^\circ$ relative to the horizon.
* **Night Mode**: Sun altitude $\le -6.0^\circ$ relative to the horizon.
* **Moon Mode**: Triggered when in Night Mode, the Moon is $> 0.0^\circ$ above the horizon, and lunar disk illumination exceeds the configured threshold (default: $> 33\%$).

Basic mode is appropriate for sensors with narrow dynamic ranges or setups where constant gain is required for standardized photometric comparison.

### B. Auto-Gain with Exposure Priority (`autogain_exposurepriority_dB.py`)
This algorithm optimizes signal-to-noise ratio (SNR) by prioritizing exposure duration over gain. It increases exposure time until reaching the configured maximum night exposure limit (e.g., 30–60 seconds). Only when maximum exposure is reached does the algorithm increase gain to maintain target frame brightness (mean ADU). Conversely, as the sky brightens, gain is reduced to baseline before exposure time is curtailed.

Because different camera manufacturers configure gain on distinct mathematical scales, select the matching sub-mode:

| Sub-Mode | Unit / Increment | Camera Platforms |
|---|---|---|
| `1/10 dB` | 0.1 dB increments | ZWO ASI, Player One Astronomy |
| `1/100 ISO` | 1/100 nominal ISO | Raspberry Pi libcamera (typical range: 1.0 to 16.0 / 22.26) |
| `Native ISO` | Direct ISO values | ToupTek, Altair Astro, Omegon, Ogma, RisingCam |
| `Native dB` | Direct dB values | Select QHY models |

Consult the [Camera Gain Reference](Camera-Gain-Reference) for vendor-specific gain ranges and unit mappings.

### C. Legacy Auto-Gain (`legacy_autogain.py`)
Divides the total camera gain range into linear increments once exposure thresholds are crossed. Because it assumes a linear gain curve, it performs sub-optimally with non-linear ISO-based sensors. It is retained solely for backward compatibility and is not recommended for new deployments.

---

## 2. Key Parameter Reference

| Parameter | Type | Default | Description |
|---|---|---|---|
| `TARGET_MEAN_DAY` | Integer | `128` | Target mean image brightness (0–255 scale in 8-bit, scaled in 16-bit) during daylight. |
| `TARGET_MEAN_NIGHT` | Integer | `35` | Target mean image brightness during night capture. |
| `EXPOSURE_MIN_DAY` | Float | `0.0001` | Minimum allowed daytime exposure duration in seconds. |
| `EXPOSURE_MAX_DAY` | Float | `1.0` | Maximum allowed daytime exposure duration in seconds. |
| `EXPOSURE_MIN_NIGHT` | Float | `1.0` | Minimum allowed nighttime exposure duration in seconds. |
| `EXPOSURE_MAX_NIGHT` | Float | `60.0` | Maximum allowed nighttime exposure duration in seconds. |
| `EXPOSURE_STEP_DAY` | Float | `0.001` | Exposure adjustment step size for daylight transitions. |
| `EXPOSURE_STEP_NIGHT` | Float | `0.5` | Exposure adjustment step size during nighttime transitions. |