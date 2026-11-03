# Satellite Tracking

`indi-allsky` tracks visual satellite passes overhead in real time, determining which spacecraft and orbital objects are within the camera field of view and rendering their positional metadata as text overlays.

> [!NOTE]
> The **Satellite Tracking** configuration tab in the web interface is hidden by default in Simple Mode. Enable **Expert Mode** via the toggle switch in the top configuration header to access satellite tracking settings.

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