# Star Trail Composite Generation

Star trail composites visually document stellar apparent motion resulting from terrestrial rotation. The algorithm combines a sequential time-series of nocturnal exposures into a single composite frame, with optional dynamic generation of accumulation timelapses.

---

## 1. Stacking Methodology

The core stacking engine (`indi_allsky/stack.py`) isolates stellar trajectories by evaluating pixels across temporal frames:

* **Maximum Pixel Value (`MAX`)**: Default mode. The brightest pixel across all valid frames is retained at each `(x, y)` coordinate. Because stellar points traverse across dark background sky, their paths coalesce into continuous arcs.
* **Average Pixel Value (`AVG`)**: Computes the mean intensity across all valid frames, smoothing transient noise while suppressing faint stars.
* **Minimum Pixel Value (`MIN`)**: Retains lowest pixel intensities, effectively erasing stars and transient objects while preserving static foreground terrain.

---

## 2. Frame Filtering Criteria

High-quality star trail composites require excluding frames affected by lunar illumination, twilight sky glow, passing clouds, or atmospheric ground fog.

> [!NOTE]
> Star trail circle masking and advanced frame filtering parameters under **Configuration** require **Expert Mode** to be enabled using the toggle switch in the top configuration header.

Under **Configuration -> Star Trails**, the following filter parameters govern frame inclusion:

| Parameter | Default | Empirical Purpose |
|---|---|---|
| **Max Sun Altitude** | `-15.0°` | Excludes frames captured when the Sun is above this altitude. Prevents solar twilight glare from obliterating faint stellar paths. |
| **Exclude Moon Mode** | `true` | Excludes exposures captured while active lunar illumination (Moon Mode) is engaged. |
| **Custom Max Moon Altitude** | `-91.0°` | Altitude threshold for lunar exclusion (-91° disables). |
| **Custom Max Moon Phase** | `101%` | Lunar illumination percentage threshold (101% disables). |
| **Min Stars Threshold** | `0` | Minimum detected star count required for frame inclusion. Frame is discarded if clouds obscure stars below this count. |
| **Max Frame ADU** | `65` | Rejects overexposed or overcast frames whose average Analog-to-Digital Unit (ADU) exceeds this ceiling. |
| **Mask Threshold ADU** | `255` | Secondary threshold targeting local light pollution or ground illumination. Evaluated in tandem with Pixel Threshold. |
| **Pixel Threshold** | `1.0%` | If the percentage of pixels exceeding `Mask Threshold ADU` is higher than this value, the frame is discarded. |
| **Use Existing Star/ADU Data**| `true` | Re-uses metrics recorded during live acquisition. Disabling forces re-evaluation during compilation. |

---

## 3. Automation and Video Accumulation

* **Automated Dawn Execution**: The daemon schedules star trail generation immediately following astronomical or nautical dawn via the background video queue (`TaskQueueQueue.VIDEO`).
* **Accumulation Timelapse**: When **Star Trails Timelapse** is enabled and the available frame count satisfies **Timelapse Minimum Frames** (default: 250), an accumulation video is encoded displaying the progressive accumulation of star arcs across the night.
* **On-Demand Regeneration**: In the web archive viewer (`/indi-allsky/images`), navigating to any historical night permits on-demand dispatch of star trail compilation tasks directly into the background queue.
 