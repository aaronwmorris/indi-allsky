# VirtualSky Integration

VirtualSky provides an interactive, calibrated celestial sphere projection aligned with allsky fisheye imagery. It calculates equatorial, alt-azimuth, and planetary positions in real time based on the camera coordinates and timestamp.

The viewer is accessible in the web dashboard at:
```
https://<allsky-host>/indi-allsky/virtualsky
```

---

## Capabilities

* **Celestial Mapping**: Renders stars, major solar system planets, and constellations directly mapped to the fisheye field of view.
* **Optical Alignment**: Supports image circle sizing, optical axis center offsets, and compass orientation adjustments.
* **Astrometric Calibration**: Integrates with the astrometric `lens_solver` to compute and apply polynomial distortion models for precise star-to-pixel registration.

---

## Configuration Reference

> [!NOTE]
> The **VirtualSky** settings card under **Configuration** → **Location** is an advanced feature visible only in **Expert Mode**. Enable Expert Mode via the toggle switch in the top configuration header to access VirtualSky settings.

Settings are managed in the web interface under **Configuration** → **Location** → **VirtualSky**:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ENABLE` | Boolean | `false` | Enables the VirtualSky rendering interface and metadata tracking. |
| `MAGNITUDE` | Float | `6.0` | Limiting visual magnitude for displayed stars. Higher values display fainter stars. |
| `CONSTELLATIONS` | Boolean | `true` | Renders constellation boundary stick lines. |
| `CONSTELLATIONLABELS` | Boolean | `false` | Renders constellation names. |
| `SHOWSTARS` | Boolean | `true` | Renders stellar objects within the limiting magnitude. |
| `SHOWSTARLABELS` | Boolean | `true` | Displays names for prominent navigational stars. |
| `SHOWPLANETS` | Boolean | `true` | Renders major solar system bodies (Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn). |
| `SHOWPLANETLABELS` | Boolean | `true` | Displays planetary name labels. |
| `IMAGE_CIRCLE_DIAMETER` | Integer | `3500` | Diameter (in pixels) of the lens projection circle on the camera sensor. |
| `OFFSET_X` | Integer | `0` | Horizontal pixel offset of the lens optical center relative to the sensor center. |
| `OFFSET_Y` | Integer | `0` | Vertical pixel offset of the lens optical center relative to the sensor center. |
| `LATITUDE_OFFSET` | Float | `0.0` | Positional offset in degrees to correct physical camera tilt or leveling error. |
| `LONGITUDE_OFFSET` | Float | `0.0` | Azimuthal offset in degrees to align camera North with geographic/astronomic North. |
| `PRECESSION` | Boolean | `false` | Applies Earth axial precession adjustments to equatorial coordinates. |
| `RADIAL_DISTORTION` | Float | `0.0` | Radial lens distortion coefficient for non-linear fisheye projections. |
| `CALIBRATION_ENABLED` | Boolean | `false` | Activates polynomial lens model coefficients computed by the astrometric solver. |

---

## Astrometric Lens Solver Alignment

Manual alignment requires matching the optical center (`OFFSET_X`, `OFFSET_Y`) and compass rotation (`LONGITUDE_OFFSET`). 

For optimal precision, utilize the built-in automated astrometric solver:
1. Capture an unclouded nighttime image with visible stars.
2. In the Image Viewer, select the lens solver utility.
3. The solver extracts star centroids, queries the embedded star catalog, fits WCS coordinates, and writes the calibrated polynomial distortion parameters (`CALIBRATION`) into the camera configuration.