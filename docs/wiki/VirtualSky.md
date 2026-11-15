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

Settings are managed in the web interface under **Configuration** → **VirtualSky**:

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

## Automatic alignment for a portable station

Under **Config → Overlays → Cardinal Directions**, enable **Align automatically from stars**. Keep the station's clock and coordinates current. VirtualSky shows **Orientation pending for this image** on photos taken before two separate night exposures agree on the orientation. Capture continues while the solver runs. For cameras pointing nearly straight up, the automatic check uses the optical axis, image rotation and projected horizon to verify that the compass marks are stable. It rechecks during the night and starts a fresh alignment after a restart, a new night, a significant location change or a gap in capture. When the sky is cloudy, it waits for usable stars.

Each confirmed exposure stores its own geometry. The compass on the original photograph and the VirtualSky overlay use the orientation for that exposure. Geographic panoramas start at north and progress east, south and west. North is up and east is left in registered keograms, star trails, and all-sky timelapses. If the camera is moved, frames from different confirmed setups can still be projected into this common sky. A selected panorama crop uses frames with the same panorama convention as its reference image.

The original photos are available throughout calibration. Direction-dependent stacks exclude unconfirmed frames. When a movie contains calibrated exposures, its geographic sequence uses those exposures. Older manual recordings retain their original geometry. To return to manual operation, turn off **Align automatically from stars**.
