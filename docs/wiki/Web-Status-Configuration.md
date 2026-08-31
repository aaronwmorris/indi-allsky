# Overview
The Web Status section can be customized using a template and python string format codes.

Information regarding python string formats may be found here:
https://docs.python.org/3/library/string.html#formatspec

Each line of the template is wrapped in `<div></div>` tags and will be rendered as HTML.  HTML tags are allowed in the template.

## Defaults
This is the default template
```
Status: {status:s}
Lat: {latitude:+0.1f}/Long: {longitude:+0.1f}
Mode: {mode:s}
Next change: {mode_next_change:s} [{mode_next_change_h:0.1f}h]
Sun: {sun_alt:0.1f}&deg; {sun_dir:s}
Moon: {moon_alt:0.1f}&deg; {moon_dir:s}
Rise: {moon_next_rise:s} [{moon_next_rise_h:0.1f}h]
Set: {moon_next_set:s} [{moon_next_set_h:0.1f}h]
Phase: {moon_phase_str:s} <span data-bs-toggle="tooltip" data-bs-placement="right" title="{moon_phase:0.0f}%">{moon_glyph:s}</span>
Smoke: {smoke_rating:s} {smoke_rating_status}
Kp-index: {kpindex:0.2f} {kpindex_rating:s} {kpindex_trend:s}
Bt: {aurora_mag_bt:0.1f}nT/Bz: {aurora_mag_gsm_bz:+0.1f}/NH: {aurora_n_hemi_gw:d}GW
Aurora: {ovation_max:d}% {aurora_data_status:s}
```

## Variables

| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| status         | str          |            | Status of indi-allsky |
| latitude       | float        |            | Latitude |
| longitude      | float        |            | Longitude |
| elevation      | int          |            | Elevation |
| sidereal_time  | str          |            | Local Sidereal time |
| mode           | str          |            | Mode (Day/Night) |
| mode_next_change   | str      | Jan 2025   | Next mode change |
| mode_next_change_h | float    | Jan 2025   | Next mode change (hours) |  
| sun_alt        | float        |            | Sun Altitude |
| sun_dir        | str          |            | Sun direction (arrow) |
| sun_next_rise  | str          | Nov 2024   | Next sunrise time |
| sun_next_rise_h | float       | Nov 2024   | Next sunrise in hours |
| sun_next_set   | str          | Nov 2024   | Next sunset time |
| sun_next_set_h | float        | Nov 2024   | next sunset in hours |
| sun_next_astro_twilight_rise   | str    | Nov 2024   | Next astro twilight (sunrise) time |
| sun_next_astro_twilight_rise_h | float  | Nov 2024   | Next astro twilight (sunrise) in hours |
| sun_next_astro_twilight_set    | str    | Nov 2024   | Next astro twilight (sunset) time |
| sun_next_astro_twilight_set_h  | float  | Nov 2024   | next astro twilight (sunset) in hours |
| moon_alt       | float        |            | Moon Altitude |
| moon_dir       | str          |            | Moon direction (arrow) |
| moon_phase_str | str          |            | Moon phase string (Waxing/Waning) |
| moon_glyph     | str          |            | Moon glyph HTML character |
| moon_phase     | float        |            | Moon phase (percentage) |
| moon_cycle_percent | float    |            | Current moon cycle percentage |
| moon_next_rise | str          | Nov 2024   | Next moon-rise time |
| moon_next_rise_h | float      | Nov 2024   | Next moon-rise in hours |
| moon_next_set  | str          | Nov 2024   | next moon-set time |
| moon_next_set_h | float       | Nov 2024   | Next moon-set in hours |
| smoke_rating   | str          |            | Smoke rating |
| smoke_rating_status | str     |            | Smoke rating data status (will indicate if data is old) |
| kpindex        | float        |            | K-P Index |
| kpindex_rating | str          |            | K-P Index text rating (LOW/HIGH) |
| kpindex_trend  | str          |            | K-P Index trend (arrow) |
| kpindex_status | str          |            | [LEGACY] K-P Index data status (will indicate if data is old) |
| ovation_max    | int          |            | Aurora Ovation score for current location |
| ovation_max_status | str      |            | [LEGACY] Aurora Ovation data status (will indicate if data is old) |
| aurora_data_status | str      | Mar 2025   | Aurora data status (will indicate if data is old) |
| aurora_mag_bt         | float | Mar 2025   | Interplanetary Magnetic Field strength [nT] - 20m average |
| aurora_mag_gsm_bz     | float | Mar 2025   | Interplanetary Magnetic Field direction (+North/-South) - 20m average |
| aurora_plasma_density | float | Mar 2025   | Solar Wind density [1/cm³] - 20m average |
| aurora_plasma_speed   | float | Mar 2025   | Solar Wind speed [km/s] - 20m average |
| aurora_plasma_temp    | int   | Mar 2025   | Solar Wind temperature [Kelvin] - 20m average |
| aurora_n_hemi_gw      | int   | Mar 2025   | Hemispheric power - Northern Hemisphere (Gigawatts) |
| aurora_s_hemi_gw      | int   | Mar 2025   | Hemispheric power - Southern Hemisphere (Gigawatts) |
| owner          | str          |            | Owner |
| location       | str          |            | Location name |
| lens_name      | str          |            | Lens description |
| alt            | float        |            | Lens Altitude |
| az             | float        |            | Lens Azimuth |
| camera_name    | str          |            | Camera INDI name |
| camera_friendly_name | str    |            | Camera friendly name (configured in DB) |

## Image Variables
These values are populated from image data.  Will only be populated if the capture process is running within the last 15 minute.

| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| exposure       | float        | Nov 2025   | Exposure in seconds |
| exp_elapsed    | float        | Nov 2025   | The amount of time it required to receive exposure since it was requested |
| gain           | float        | Nov 2025   | Gain |
| binmode        | int          | Nov 2025   | Bin mode |
| temp           | float        | Nov 2025   | Image sensor temperature |
| adu            | float        | Nov 2025   | Image adu |
| sqm            | float        | Nov 2025   | Janky SQM |
| stars          | int          | Nov 2025   | Star count |
| detections     | int          | Nov 2025   | Line/Meteor count |
| process_elapsed | float       | Nov 2025   | Image processing time |
| dew_heater_status | str       | Nov 2025   | Dew Heater Status |
| fan_status     | str          | Nov 2025   | Fan Status |
| wind_dir       | str          | Nov 2025   | Wind direction |
| sensor_temp_0<br>sensor_temp_1<br>...<br>sensor_temp_59 | float | Nov 2025 | System temperatures as reported by psutil |
| camera_sqm_raw_mag | float    | Feb 2026   | Camera SQM Raw Magnitude |
| sensor_user_0  | float        | Nov 2025   | Camera Temperature |
| sensor_user_1  | float        | Nov 2025   | Dew Heater Duty Cycle |
| sensor_user_2  | float        | Nov 2025   | Dew Point |
| sensor_user_3  | float        | Nov 2025   | Frost Point |
| sensor_user_4  | float        | Nov 2025   | Fan Duty Cycle |
| sensor_user_5  | float        | Nov 2025   | Heat Index |
| sensor_user_6  | float        | Nov 2025   | Wind direction (degrees) |
| sensor_user_7  | float        | Nov 2025   | Device SQM Magnitude |
| sensor_user_8  | float        | Feb 2026   | Camera SQM Magnitude |
| sensor_user_9  | float        | Feb 2026   | Camera SQM ADU |
| sensor_user_10<br>sensor_user_11<br>...<br>sensor_user_59 | float | May 2024 | Temperature, Humidity, etc data |

