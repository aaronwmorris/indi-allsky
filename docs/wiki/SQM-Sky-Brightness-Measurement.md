# Overview
indi-allsky now has the capability of being used to create objective Sky Quality Meter [SQM] brightness measurements.  Configuration is available to take periodic exposures at a fixed exposure and gain to objectively measure the amount of light hitting the sensor.

Every SQM measurement will be taken at the same exposure, gain, and binning setting, regardless of what exposure and gain are being used to create images.  SQM measurements will only occur during astronomical darkness when the sun is less than -18° below the horizon.

The default period for SQM measurements is every 15 minutes (900 seconds) and is adjustable.

Dark frames are utilized to subtract the floor of the camera noise from the signal.

## Camera RAW mode
It is strongly encouraged that your camera be in RAW mode/16-bit mode to provide the greatest dynamic range.  8-bit [RGB24] mode will still provide measurements, but the debayering process for color images alters the ADU values.

If an RGB image is encountered, only the green channel is used for brightness measurements.

## Exposure
The exposure from your camera should be at least 1.0s to ensure linearity of the sensor.  It is recommended that your ADU values be greater than 200 for your darkest measurements, as well.  ADU measurements should not exceed the 50% range for your sensor.

* 16-bit camera - 32767 (65335 / 2)
* 14-bit camera - 8191 (16383 / 2)
* 12-bit camera - 2047 (4095 / 2)
* 10-bit camera - 511 (1023 / 2)
* 8-bit camera  - 127 (255 / 2)


## Raw Magnitude
The average ADU measurement [Analog-to-Digital Unit] of the central part of the image is taken and a "raw magnitude" calculated using the following formula:

    raw_magnitude = -log10(adu) * 2.5

This results in a negative relative magnitude which can be offset to determine absolute magnitude.


## Magnitude Offset calibration
The magnitude offset is added to the relative, raw magnitude to calculate the absolute magnitude.  Using a calibrated SQM meter is the best possible scenario to determine the offset.

**You should wait until a you have a moonless, cloudless, clear night to calibrate.**  Let the camera take an SQM exposure to generate a raw magnitude.

Assuming your actual sky magnitude is `21.5` and the raw magnitude generated is `-6.512`.  You would add `21.5` to `abs(-6.512)` which results in `28.012`.  This would be your Magnitude Offset.  All future SQM readings will use this fixed offset.

You may also use https://www.lightpollutionmap.info/ as the basis for determining the correct offset to determine real magnitude.  Without a calibrated SQM measurement, this is mostly an **educated guess**.


## Unity Gain
Unity gain is the gain level for a sensor where one electron volt equals one ADU of signal (e-/ADU).  "Brightness" increases relative to the number of photons received.  Unity gain is significant because the ADU measurement is directly proportional and linear to the number of photons received (therefore brightness).

For example, at unity gain... If 100 photons generates one electron volt of signal (1 ADU), 200 photons will result in 2 ADU.  300 photons will be 3 ADU, etc.


### Camera Unity Gains
| Camera                 | Unity Gain | Note |
| ---------------------- | ---------- | ---- |
| Raspberry Pi HQ Camera | 6.4<br>2.13 (6.57 dB) | According to AI |
| ZWO ASI676MC/MM        | 82         |      |
| ZWO ASI678MC           | 85         |      |
| ZWO ASI662MC           | 195        |      |
| ZWO ASI462MC           | 90         |      |
| ZWO ASI585MC           | 195        |      |
| ZWO ASI120MC/MM        | 29         |      |
| ZWO ASI220MC           | 68         |      |
| ZWO ASI224MC           | 135        |      |
| ZWO ASI290MC/MM        | 110        |      |
| ZWO ASI174             | 179        |      |
| ZWO ASI385MC           | 135        |      |

* Note: Binning might alter the unity gain point for the camera.  Effects of binning to unity gain are not well documented.


## Unsupported Configs
Specialty cameras such as Network IP web cameras are not suitable to the task of measuring sky brightness.  These cameras generally do not permit control of exposure or gain, and there for cannot provide valid measurements.