# Touptek Camera Known Issues

## Altair Image corruption
Altair cameras are known to start in an odd mode where the image is corrupted into 4 overlapping images with a black bar at the top.  This can affect other Touptek cameras, too.

* https://github.com/aaronwmorris/indi-allsky/issues/1840
* https://github.com/aaronwmorris/indi-allsky/discussions/2397

Setting the to RAW mode will correct this issue.

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

## Default resolution
Touptek/Altair cameras usually start in a low resolution mode.  Additional config parameters are needed for higher resolutions.

### Touptek AE676c
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

### Altair GPCAM3 678
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

### Altair Hypercam 178C
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
### Altair 290C resolution
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

### Altair 224C resolution
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