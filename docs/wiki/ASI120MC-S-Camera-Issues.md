# Overview

## Gain bug
The ASI120MC-S (and MM) have a strange behavior issue when the gain is changed during the day-night transitions.  A few frames after the gain is changed, the camera experiences an exposure timeout.

Within the indi_asi code base, in asi_base.cpp, the indi server will try to transition the bit depth from 16-bit to 8-bit.  This [temporarily] corrects the exposure issue, albeit, the camera now runs in 8-bit mode instead of 16-bit.  Eventually, when the camera transitions from day/night later while in 8-bit mode, the camera will stop responding altogether.

Relevant code:  https://github.com/indilib/indi-3rdparty/blob/master/indi-asi/asi_base.cpp#L249

### The fix
indi-allsky has a bit of code to workaround this issue.  Periodically (every ~3 minutes), indi-allsky will re-apply the `INDI_CONFIG_DEFAULTS` config options.  When the code changes the gain, resulting in the camera transitioning to 8-bit mode, within 5 minutes, the INDI_CONFIG_DEFAULTS options will allow the camera to be put back into 16-bit mode.

### INDI_CONFIG_DEFAULTS
The following config is necessary to force the camera back into 16-bit mode.
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_VIDEO_FORMAT": {
            "on": [
                "ASI_IMG_RAW16"
            ],
            "off": [
                "ASI_IMG_RAW8"
            ]
        }
    }
}
```

## Black Bar/Image glitch
You may receive images with a black bar on one side of the image or the image is glitchy.  This can be resolved by setting the USB Bandwidth to 100.

* https://github.com/aaronwmorris/indi-allsky/issues/2125
* https://bbs.zwoastro.com/d/11923-firmware-bug-asi120mm-mini/11

```json
{
    "PROPERTIES": {
      "CCD_CONTROLS": {
        "BandWidth": 100
      }
    },
    "SWITCHES": {
      "CCD_VIDEO_FORMAT": {
        "on": [
          "ASI_IMG_RAW16"
        ],
        "off": [
          "ASI_IMG_RAW8"
        ]
      }
    }
}
```