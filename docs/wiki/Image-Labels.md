# Overview
The image label can now be customized using a template and python string format codes.

Information regarding python string formats may be found here:
https://docs.python.org/3/library/string.html#formatspec

## Defaults
This is the default template
```
# size:30 [Use 60 for higher resolution cameras]
# xy:-15,15 (Upper Right)
# anchor:ra (Right Justified)
# color:150,0,0
{timestamp:%Y.%m.%d %H:%M:%S}
# color:100,100,0
Lat {latitude:+0.0f} Long {longitude:+0.0f}
# color:150,150,150
Tiangong {tiangong_up:s} [{tiangong_next_h:0.1f}h/{tiangong_next_alt:0.0f}°]
Hubble {hst_up:s} [{hst_next_h:0.1f}h/{hst_next_alt:0.0f}°]
ISS {iss_up:s} [{iss_next_h:0.1f}h/{iss_next_alt:0.0f}°]
# xy:-15,-240 (Lower Right) [Use -15,-450 for size 60]
# color:175,175,0
Sun {sun_alt:0.0f}°
# color:125,0,0
Mercury {mercury_alt:0.0f}°
# color:100,150,150
Venus {venus_alt:0.0f}°
# color:150,0,0
Mars {mars_alt:0.0f}°
# color:100,100,0
Jupiter {jupiter_alt:0.0f}°
# color:100,100,150
Saturn {saturn_alt:0.0f}°
# color:150,150,150
Moon {moon_phase:0.0f}% {moon_alt:0.0f}°
# xy:15,-120 (Lower Left)  [Use 15,-210 for size 60]
# anchor:la (Left Justified)
# color:0,150,150
Stars {stars:d}
# color:150,50,50
Kp-index {kpindex:0.2f}
# color:150,150,150
Smoke {smoke_rating:s}
# xy:15,15 (Upper Left)
# color:0,150,0
Exposure {exposure:0.6f}
# color:150,50,0
Gain {gain_f:0.2f}
# color:50,50,150
Camera {temp:0.1f}°{temp_unit:s}
# color:150,0,150
Stretch {stretch:s}
Stacking {stack_method:s}
# color:200,200,200 (default color)
# additional labels (Moon Mode) will be added here
```

_Note: Leave enough room for additional labels after your last entry.  indi-allsky will add additional labels such as moon mode and eclipse info at the end.  It is best to return to the upper left or right so that space is available._

## Label Colors
The color of the text may be changed by adding a formatted comment `color:#,#,#` The numbers are RGB color codes.  The color is persistent for all subsequent lines and can be changed as many times as you wish.
```
# default color is used if none specified
{timestamp:%Y.%m.%d %H:%M:%S}
# color:255,0,0  additional text is ignored
Lat {latitude:0.1f} Long {longitude:0.1f}
# comment does nothing
# color:0,255,0
Exposure {exposure:0.6f}
```

## Label Location
The location of the text can be changed using `xy:#,#` The numbers are X,Y coordinates.  The coordinates are persistent for all subsequent lines and can be changed as many times as you wish.

A negative X coordinate will offset from the right side of the image.

A negative Y coordinate will offset from the bottom of the image.

```
# xy:100,200 color:0,255,0  coordinates may be combined with color
{timestamp:%Y.%m.%d %H:%M:%S}
Lat {latitude:0.1f} Long {longitude:0.1f}
Exposure {exposure:0.6f}
```

## Text justification (Pillow-only)
If you want to right (or center) justify your text, you can add an anchor configuration for Pillow.  A `ra` anchor combined with negative offsets will draw the text offset from the right/bottom of the image.

The default anchor is `la` for left-ascender.

```
{timestamp:%Y.%m.%d %H:%M:%S}
# xy:-30,30 anchor:ra   right-ascender  This will draw text offset from the right top of the image.
Lat {latitude:0.1f} Long {longitude:0.1f}
# xy:30,60 anchor:la  left-ascender  Return to original location
Exposure {exposure:0.6f}
```

https://pillow.readthedocs.io/en/stable/handbook/text-anchors.html#text-anchors

## Text size (Pillow-only)

```
{timestamp:%Y.%m.%d %H:%M:%S}
# size:40
Lat {latitude:0.1f} Long {longitude:0.1f}
# size:30
Exposure {exposure:0.6f}
```

## OpenCV vs Pillow
OpenCV only supports ASCII characters and limited internal fonts.  Pillow is much more capable with TrueType font support.


## Variables

| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| timestamp      | datetime     |            | https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes |
| ts             | datetime     |            | Shortcut for `timestamp` |
| timestamp_utc  | datetime     | Dec 2025   | Datetime in UTC |
| ts_utc         | datetime     | Dec 2025   | Shortcut for `timestamp_utc` |
| exposure       | float        |            | Image exposure |
| day_date       | date         |            | Day reference for exposure.  Referencing the date when the timelapse set starts. |
| rational_exp   | str          |            | Rational Exposure eg `1 1/4` (a work in progress) |
| gain           | int          |            | Camera gain |
| temp           | float        |            | Camera temperature |
| temp_unit      | str          |            | Temperature unit |
| sqm            | float        |            | SQM average |
| camera_sqm_raw_mag | float    | Feb 2026   | Camera SQM Raw Magnitude measurement |
| stars          | int          |            | Star count |
| detections     | str          |            | Line detections (True or False) |
| owner          | str          |            | Camera owner |
| location       | str          |            | Camera location |
| kpindex        | float        |            | Global Kp-index value |
| ovation_max    | int          |            | Percentage chance of aurora visibility |
| aurora_mag_bt  | float        | Mar 2025   | Interplanetary Magnetic Field strength [nT] - 20m average |
| aurora_mag_gsm_bz     | float | Mar 2025   | Interplanetary Magnetic Field direction (North/South) - 20m average  |
| aurora_plasma_density | float | Mar 2025   | Solar Wind density [1/cm³] - 20m average |
| aurora_plasma_speed   | float | Mar 2025   | Solar Wind speed [km/s] - 20m average |
| aurora_plasma_temp    | int   | Mar 2025   | Solar Wind temperature [Kelvin] - 20m average |
| aurora_n_hemi_gw      | int   | Mar 2025   | Hemispheric power - Northern Hemisphere [Gigawatts] |
| aurora_s_hemi_gw      | int   | Mar 2025   | Hemispheric power - Southern Hemisphere [Gigawatts] |
| smoke_rating   | str          |            | Smoke rating for your location NOAA *(North America only)* |
| sun_alt        | float        |            | Sun altitude |
| sun_up         | str          | Nov 2025   | Sun above horizon |
| sun_next_rise  | str          | Nov 2024   | Next sunrise time |
| sun_next_rise_h | float       | Nov 2024   | Next sunrise in hours |
| sun_next_set   | str          | Nov 2024   | Next sunset time |
| sun_next_set_h | float        | Nov 2024   | next sunset in hours |
| sun_next_astro_twilight_rise   | str    | Nov 2024   | Next astro twilight (sunrise) time |
| sun_next_astro_twilight_rise_h | float  | Nov 2024   | Next astro twilight (sunrise) in hours |
| sun_next_astro_twilight_set    | str    | Nov 2024   | Next astro twilight (sunset) time |
| sun_next_astro_twilight_set_h  | float  | Nov 2024   | next astro twilight (sunset) in hours |
| moon_alt       | float        |            | Moon altitude |
| moon_phase     | float        |            | Moon phase percentage |
| moon_cycle     | float        |            | Moon cycle percentage |
| moon_up        | str          |            | Moon above horizon |
| moon_next_rise | str          | Nov 2024   | Next moon-rise time |
| moon_next_rise_h | float      | Nov 2024   | Next moon-rise in hours |
| moon_next_set  | str          | Nov 2024   | Next moon-set time |
| moon_next_set_h | float       | Nov 2024   | Next moon-set in hours |
| sun_moon_sep   | float        |            | Angular separation of sun and moon |
| latitude       | float        |            | Latitude |
| longitude      | float        |            | Longitude |
| sidereal_time  | str          |            | Local apparent sidereal time |
| stretch        | str          |            | Stretch enabled |
| stretch_m1_gamma   | float    |            | Stretch Mode1 Gamma |
| stretch_m1_stddevs | float    |            | Stretch Mode1 Standard Deviation cutoff |
| stack_method   | str          |            | Stacking method |
| stack_count    | int          |            | Stack count |
| mercury_alt    | float        |            | Mercury altitude |
| mercury_up     | str          |            | Mercury above horizon |
| venus_alt      | float        |            | Venus altitude |
| venus_phase    | float        |            | Venus phase percentage |
| venus_up       | str          |            | Venus above horizon |
| mars_alt       | float        |            | Mars altitude |
| mars_up        | str          |            | Mars above horizon |
| jupiter_alt    | float        |            | Jupiter altitude |
| jupiter_up     | str          |            | Jupiter above horizon |
| saturn_alt     | float        |            | Saturn altitude |
| saturn_up      | str          |            | Saturn above horizon |
| iss_alt        | float        | Sept 2023  | ISS altitude |
| iss_up         | str          | Sept 2023  | ISS above horizon |
| iss_next_h     | float        | Sept 2023  | Next ISS pass in hours |
| iss_next_alt   | float        | Sept 2023  | Next ISS max altitude |
| hst_alt        | float        | Sept 2023  | Hubble altitude |
| hst_up         | str          | Sept 2023  | Hubble above horizon |
| hst_next_h     | float        | Sept 2023  | Next Hubble pass in hours |
| hst_next_alt   | float        | Sept 2023  | Next Hubble max altitude |
| tiangong_alt        | float   | Feb 2024   | Tiangong altitude |
| tiangong_up         | str     | Feb 2024   | Tiangong above horizon |
| tiangong_next_h     | float   | Feb 2024   | Next Tiangong pass in hours |
| tiangong_next_alt   | float   | Feb 2024   | Next Tiangong max altitude |


## System Temperature Sensors
**Note:  Each system temperature is available with a `_f` `_c` and `_k` suffix for a fixed unit**

| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| sensor_temp_0<br>sensor_temp_0_f<br>sensor_temp_0_c<br>sensor_temp_0_k | float        | May 2024   | Camera Temperature |
| sensor_temp_1  | float        | May 2024   | Reserved |
| sensor_temp_2  | float        | May 2024   | Reserved |
| sensor_temp_3  | float        | May 2024   | Reserved |
| sensor_temp_4  | float        | May 2024   | Reserved |
| sensor_temp_5  | float        | May 2024   | Reserved |
| sensor_temp_6  | float        | May 2024   | Reserved |
| sensor_temp_7  | float        | May 2024   | Reserved |
| sensor_temp_8  | float        | May 2024   | Reserved |
| sensor_temp_9  | float        | May 2024   | Reserved |
| sensor_temp_10<br>sensor_temp_11<br>...<br>sensor_temp_59  | float        | May 2024   | System temperatures as reported by psutil |

* Raspberry Pi 3/4 - `sensor_temp_10` should be the CPU temperature
* Raspberry Pi 5 - `sensor_temp_10` should be CPU, `sensor_temp_11` the GPU

## User Sensors
| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| dew_heater_status | str       | May 2024   | Dew Heater Status |
| fan_status     | str          | June 2024  | Fan Status |
| wind_dir       | str          | June 2024  | Wind direction |
| camera_sqm_raw_mag | float    | Feb 2026   | Camera SQM Raw Magnitude |
| sensor_user_0  | float        | May 2024   | Camera Temperature |
| sensor_user_1  | float        | May 2024   | Dew Heater Duty Cycle |
| sensor_user_2  | float        | May 2024   | Dew Point |
| sensor_user_3  | float        | May 2024   | Frost Point |
| sensor_user_4  | float        | May 2024   | Fan Duty Cycle |
| sensor_user_5  | float        | June 2024  | Heat Index |
| sensor_user_6  | float        | June 2024  | Wind direction (degrees) |
| sensor_user_7  | float        | June 2024  | Device SQM Magnitude |
| sensor_user_8  | float        | Feb 2026   | Camera SQM Magnitude |
| sensor_user_9  | float        | Feb 2026   | Camera SQM ADU |
| sensor_user_10<br>sensor_user_11<br>...<br>sensor_user_59  | float        | May 2024   | Temperature, Humidity, etc data |

## Custom slots
Use these slots to add custom values to the overlay (in `indi-allsky/processing.py`)
| Name           | Type         | Add Date   | Info |
| -------------- | ------------ | ---------- | ---- |
| custom_1            |         | June 2025  | Custom data |
| custom_2            |         | June 2025  | Custom data |
| custom_3            |         | June 2025  | Custom data |
| custom_4            |         | June 2025  | Custom data |
| custom_5            |         | June 2025  | Custom data |
| custom_6            |         | June 2025  | Custom data |
| custom_7            |         | June 2025  | Custom data |
| custom_8            |         | June 2025  | Custom data |
| custom_9            |         | June 2025  | Custom data |


## Full example
```
# rainbows!
{timestamp:%Y.%m.%d %H:%M:%S}
# color:255,0,0 red
{sidereal_time:s}
# color:255,165,0 orange
Lat {latitude:0.1f} Long {longitude:0.1f}
# color:255,255,0 yellow
Exposure {exposure:0.6f}
# color:0,255,0 green
Day {day_date:%Y-%m-%d}
# color:0,0,255 blue
Gain {gain:d}
# color:75,0,130 indigo
Temp {temp:0.1f}{temp_unit:s}
# color:127,0,255 violet
Stretch {stretch:s}
# color:255,0,0
Stretch Gamma {stretch_m1_gamma:0.1f}
# color:255,165,0
Stretch StdDevs {stretch_m1_stddevs:0.2f}
# color:255,255,0
Stacking {stack_method:s}
# color:0,255,0
Stack Count {stack_count:d}
# color:0,0,255
Stars {stars:d}
# color:75,0,130
SQM {sqm:0.0f}
# color:127,0,255
Detections {detections:s}
# color:255,0,0
Sun Alt {sun_alt:0.1f}
# color:255,165,0
Moon Alt {moon_alt:0.1f}
# color:255,255,0
Moon Phase {moon_phase:0.1f}%
# color:0,255,0
Moon {moon_up:s}
# color:0,0,255
Sun/Moon Separation {sun_moon_sep:0.1f}
# color:75,0,130
Mercury {mercury_alt:0.1f} {mercury_up:s}
# color:127,0,255
Venus {venus_alt:0.1f} {venus_up:s}
# color:255,0,0
Venus Phase: {venus_phase:0.1f}%
# color:255,165,0
Mars {mars_alt:0.1f} {mars_up:s}
# color:255,255,0
Jupiter {jupiter_alt:0.1f} {jupiter_up:s}
# color:0,255,0
Saturn {saturn_alt:0.1f} {saturn_up:s}
# color:0,0,255
Smoke {smoke_rating:s}
```

Character test
```
abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMNOPQRSTUVWXYZ
0123456789
`~!@#$%^&*()-_=+[]\|;:'",<.>/?~
# These glyphs will only work with Pillow (not OpenCV)
¡¢£¤¥§©«»®°±¹²³µ™¶¼½¾¿÷ƒΔÀËÏÑÜßãäëñöΩπ∞€
```