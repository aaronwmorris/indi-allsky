# Satellite Tracking

`indi-allsky` tracks visual satellite passes overhead in real time, determining which spacecraft and orbital objects are within the camera field of view and rendering their positional metadata as text overlays.

---

## 1. TLE Orbital Data Synchronization

Satellite orbital ephemerides are retrieved automatically from **CelesTrak**:
* **Catalog**: 100+ Brightest Visual Satellites (`GROUP=visual`), including the International Space Station (ISS), CSS Tiangong, Hubble Space Telescope (HST), and prominent rocket bodies.
* **Storage**: Stored in the database table `tledata` (`IndiAllSkyDbTleDataTable`).
* **Refresh Frequency**: Polled every 24 hours. If CelesTrak returns rate-limit or network errors, an exponential backoff schedule delays subsequent requests.

---

## 2. Ephemeris & Visibility Calculation

When processing an image frame:
1. `indi-allsky` propagates satellite orbits using the SGP4 orbital model paired with the observatory's latitude, longitude, and elevation.
2. The system checks if any satellite has an altitude above the local horizon threshold.
3. If an object is visible, its coordinates and photometric properties are exposed as image annotation tokens.

---

## 3. Image Overlay Variables

Satellite telemetry tokens can be embedded into custom image label templates under **Configuration** → **Image Overlays** → **Image Labels**:

| Token Variable | Type | Description | Example Output |
|---|---|---|---|
| `{satellite.title}` | String | Name of the visible satellite. | `ISS (ZARYA)` |
| `{satellite.alt}` | Float | Angular altitude above the local horizon (degrees). | `42.5` |
| `{satellite.az}` | Float | Azimuth bearing (degrees clockwise from North). | `215.3` |
| `{satellite.dir}` | String | Cardinal compass direction from the observer. | `SW` |
| `{satellite.mag}` | Float | Estimated visual magnitude ($m_v$). | `-2.1` |
| `{satellite.elevation}` | Float | Orbital altitude (elevation) above sea level in kilometers. | `418.2` |
| `{satellite.range}` | Float | Slant range distance from the observer to the spacecraft (km). | `612.4` |
| `{satellite.range_velocity}` | Float | Radial velocity relative to the observer (km/s). | `-6.8` |
| `{satellite.latitude}` | Float | Sub-satellite geocentric latitude. | `28.52` |
| `{satellite.longitude}` | Float | Sub-satellite geocentric longitude. | `-80.68` |

### Sample Overlay Template
```text
Satellite: {satellite.title} | Alt: {satellite.alt:.1f}° | Az: {satellite.az:.1f}° ({satellite.dir}) | Mag: {satellite.mag:.1f}
```

---

## 4. Satellite Reticle Overlay
`indi-allsky` can project each visible satellite's `(alt, az)` position onto the allsky image view as a circle, crosshair, or both, with an optional satellite name (`title`).

### Burned-In Image Overlay
Configured under the **Satellite** tab in the Web UI (or `SATELLITE_TRACK` in `config.json`):
* **Enable Image Reticle Overlay (`OVERLAY_ENABLE`)**: Draws reticles onto saved images during image labeling using the exposure midpoint UTC timestamp.
* **Reticle Style (`OVERLAY_STYLE`)**: `circle`, `cross`, or `both`.
* **Reticle Size (`OVERLAY_RADIUS`)**: Radius / half-size in pixels (default `15`).
* **Show Satellite Name on Reticle (`OVERLAY_LABEL_ENABLE`)**: Renders the satellite `title` next to each reticle.
* Advanced JSON defaults: `OVERLAY_THICKNESS` (`2`) and `OVERLAY_COLOR` (`[163, 230, 53]`).

### VirtualSky Web UI Overlay
In **Tools → VirtualSky**, use the **Satellites** toggle and reticle style selector (`Circle`, `Crosshair`, `Both`) under **Display only** to render satellite reticles dynamically on the browser canvas without modifying archived images. When a solved **VirtualSky** lens calibration is enabled and valid, its distortion model is applied automatically to both burned-in and Web UI reticles.