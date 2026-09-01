# Overview
The Exposure Mode function allows you to customize the exposure behavior of your all sky system.  Image brightness can be controlled by adjusting the exposure or gain settings for the camera.

## Basic
Basic exposure mode utilizes a fixed gain at each Camera Mode of Day, Night, and Moon Mode.  In this mode, the camera is set to a fixed gain and only exposure is utilized to maintain the brightness of the scene.  The camera mode is determined by the angular altitude of the sun (day vs night) and the moon (night vs moon mode).

The default settings are:
* Day - Sun is greater than -6.0 degrees from the horizon
* Night - Sun is less than -6.0 degrees from the horizon
  * Moon Mode - The camera has to be in night mode, and the moon is more than 33% illuminated and above 0 degrees of the horizon


## Exposure Priority - Auto-Gain
Auto-Gain with Exposure Priority uses both gain and exposure to maintain the brightness of the image.  Preference is given to maximize the exposure and adjusting gain once maximum exposure is reached.

This algorithm natively manages the camera's gain based on how the gain setting relates to gain in decibels [dB].  For this reason, it is necessary to select the proper sub-mode for the algorithm.

There are 4 sub-modes for Exposure Priority Auto-Gain:
* `1/10 dB` - This is for cameras that express gain via 0.1 dB increments.  Specifically ZWO ASI and PlayerOne Astronomy cameras.
* `1/100 ISO` - libcamera configures gain in increments of 1/100 of ISO.  Nominal gains are 1 to 16 or 22.26.
* `Native ISO` - This mode is for cameras that express gain directly in ISO like ToupTek, Altair, Omegon, OGMA, RisingCam, etc.
* `Native dB` - Some QHY models configure gain directly in dB units.


## Legacy Auto-Gain

The Legacy Auto-Gain algorithm was developed as an initial attempt to implement an Auto-Gain function to give Exposure priority.  It works by dividing the camera gain range down into even steps and slowly incrementing through these steps once thresholds had been met for exposure.

The legacy mode only worked as expected with cameras that express gain using dB natively.  Cameras that use ISO as a reference did not function well with this algorithm.

When I initially developed this algorithm, I did not understand how gain worked objectively and as a result, this algorithm was a poor implementation.  It is NOT recommended for use.


## Camera Gain Reference
https://github.com/aaronwmorris/indi-allsky/wiki/Camera-Gain-Reference