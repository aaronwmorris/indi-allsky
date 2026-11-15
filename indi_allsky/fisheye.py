"""Fisheye sky-to-pixel projection shared by capture, media workers and lens solving."""
import numpy


SIN45 = 0.70710678            # constant from virtualsky.js fisheye projection


def cameraAltAz(alt_rad, az_rad, lens_altitude=90.0, pointing_azimuth=0.0):
    """Rotate geographic alt/az (radians) into lens coordinates (radians).

    Lens altitude is degrees above the horizon; pointing azimuth is degrees
    east of north. Image roll is applied separately by projectToPixels.
    Keep this rotation in sync with VirtualSky.fisheyeAltAz in virtualsky.js.
    """
    # Preserve the exact legacy projection, including cameras without metadata.
    if lens_altitude is None or lens_altitude == 90.0:
        return alt_rad, az_rad
    tilt = numpy.radians(90.0 - lens_altitude)
    heading = numpy.radians(pointing_azimuth)
    across = numpy.cos(alt_rad) * numpy.sin(az_rad - heading)
    along = numpy.cos(alt_rad) * numpy.cos(az_rad - heading)
    up = numpy.sin(alt_rad)
    # Tilt in the along/up plane; the component across the heading is unchanged.
    forward = numpy.cos(tilt) * along - numpy.sin(tilt) * up
    axis = numpy.sin(tilt) * along + numpy.cos(tilt) * up
    return (numpy.arctan2(axis, numpy.hypot(across, forward)),
            heading + numpy.arctan2(across, forward))


def projectToPixels(alt_rad, az_rad, params, image_width, image_height, mirror=False,
                    lens_altitude=90.0, pointing_azimuth=0.0):
    """Project alt/az to pixels via VirtualSky's fisheye model.
    params: [azimuth_deg, lat_off_deg, long_off_deg, diameter_px,
    offset_x_px, offset_y_px]; the lat/long offsets (1, 2) are applied by
    the caller before predictAltAz, not here. Optional params[6] is lens
    curvature; omitting it preserves the original equisolid projection exactly.
    """
    alt_rad, az_rad = cameraAltAz(alt_rad, az_rad, lens_altitude, pointing_azimuth)
    azimuth_deg = params[0]
    diameter = params[3]
    offset_x = params[4]
    offset_y = params[5]

    cx = image_width / 2.0 + offset_x
    cy = image_height / 2.0 - offset_y

    theta = (numpy.pi / 2.0) - alt_rad
    r = (diameter / 2.0) * numpy.sin(theta / 2.0) / SIN45
    if len(params) > 6 and params[6]:
        # r = sin(theta) / (1+cos(theta))**(0.5+k), normalized at 90 degrees.
        # k=0: equisolid; -0.5: orthographic; +0.5: stereographic. Unlike a
        # truncated polynomial this handles those common lenses exactly.
        r *= numpy.maximum(2-(r / (diameter / 2.0))**2, 1e-12)**(-params[6])

    psi = az_rad - numpy.radians(azimuth_deg)

    sign = 1.0 if mirror else -1.0
    x = cx + sign * r * numpy.sin(psi)
    y = cy - r * numpy.cos(psi)

    return x, y
