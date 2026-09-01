# Overview

The orbs functionality in indi-allsky display the relative location of the Sun and Moon using one of three measurements:

* Local Hour Angle
* Azimuth
* Altitude


### Sun altitude marks
The tick marks on the side represent the relative measurement of 0, -6, -12, and -18 degrees of altitude of the Sun for each mode.  The larger mark indicates the target Sun altitude separating day and night time modes.

## Local Hour Angle
The orbs on the image are rendered as if the straight lines on the image were a round clock.  Top center is 12:00.  When the sun reaches the meridian is the 12:00 position, local hour angle.


## Azimuth
The orbs will be rendered as if the top center point of the image is 0 degrees azimuth.  The azimuth is the the angular distance of an object from north/south from your local position on the surface of the Earth.


## Altitude
The orbs are rendered on the right or left side of the image depending on if the Sun/Moon is increasing or decreasing in altitude, respectively.  The altitude is relative to your position on Earth.  The sides of the image represents +90 to -90 degrees.  The orbs will rarely reach the very top or bottom

## Options

### Azimuth Offset
You can configure an offset for the azimuth to match the orientation of the camera.  Only valid for `Local Hour Angle` and `Azimuth` modes.

### Reverse Orb Motion
If the image is flipped, you may reverse the orb motion to match the image orientation.  Only valid for `Local Hour Angle` and `Azimuth` modes.
