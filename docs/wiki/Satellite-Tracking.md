# Overview
indi-allsky is able to track satellites and label which might be visible in your pictures.  Currently, only the [100 (or so) Brightest](https://celestrak.org/NORAD/elements/table.php?GROUP=visual&FORMAT=tle) list from CelesTrak is tracked.

## Label Variables
| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| title          | str          |            | Satellite name |
| alt            | float        |            | Angular altitude |
| az             | float        |            | Azimuth |
| dir            | str          |            | Cardinal direction from observer |
| elevation      | float        |            | Elevation (km) above sea level (WGS66) |
| mag            | float        |            | Magnitude (max) |
| sublat         | float        |            | Geocentric latitude |
| latitude       | float        |            | Alias of sublat |
| sublong        | float        |            | Geocentric longitude |
| longitude      | float        |            | Alias of sublong |
| range          | float        |            | Range (km) from observer |
| range_velocity | float        |            | Range rate of change |