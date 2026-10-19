# ToupTek and Altair Camera Known Issues & Optimizations

Cameras utilizing ToupTek mainboards and OEM derivatives (including Altair Astro, Omegon, RisingTech, MallinCam, and Ogma) operate under the `indi_toupcam_ccd` or `indi_altair_ccd` drivers. Specific hardware models exhibit documented idiosyncrasies requiring custom driver configuration.

---

## 1. Frame Quadrant Artifacts (Overlapping Quads)

### Symptom
Certain Altair and ToupTek models (notably IMX585, IMX571, and IMX290 variants) intermittently initialize with severely corrupted frames displaying four horizontally and vertically shifted sub-quadrants divided by a black band at the top of the frame.

### Root Cause
This artifact is caused by the camera driver defaulting to an RGB demosaicing mode using incomplete or unaligned frame buffers rather than direct sensor bayer readout.

### Resolution
Force the driver to stream frames in native `INDI_RAW` format. In the camera configuration (**INDI Configuration -> Custom Properties / Switches**), define:

```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```

Reference discussions:
* [GitHub Issue #1840](https://github.com/aaronwmorris/indi-allsky/issues/1840)
* [GitHub Discussion #2397](https://github.com/aaronwmorris/indi-allsky/discussions/2397)

---

## 2. Sensor Resolution and Conversion Gain Presets

ToupTek camera drivers frequently initialize in a binned or lower-resolution preview mode by default. To operate at maximum optical resolution and optimize conversion gain, insert the appropriate switch configurations:

### ToupTek ATR3CMOS / AE676C (Sony IMX676)
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "3536 x 3536"
            ]
        },
        "TC_CONVERSION_GAIN": {
            "on": [
                "GAIN_HIGH"
            ],
            "off": [
                "GAIN_LOW"
            ]
        },
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```

### Altair GPCAM3 678C (Sony IMX678)
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "3840 x 2160"
            ]
        },
        "TC_CONVERSION_GAIN": {
            "on": [
                "GAIN_HIGH"
            ],
            "off": [
                "GAIN_LOW"
            ]
        },
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```

### Altair Hypercam 178C (Sony IMX178)
```json
{
    "PROPERTIES": {
        "CCD_CONTROLS": {
            "BandWidth": 40
        }
    },
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "3040 x 2048"
            ]
        },
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```

### Altair GPCAM2 / GPCAM3 290C (Sony IMX290)
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "1920 x 1080"
            ]
        },
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```

### Altair GPCAM2 224C (Sony IMX224)
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "1280 x 960"
            ]
        },
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "INDI_RAW"
            ]
        }
    }
}
```