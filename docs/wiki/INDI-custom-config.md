# Overview
INDI provides a common interface for configuring astronomy equipment, but each device and vendor has custom options that can be configured via the custom INDI options.

## Format
The configuration format is JSON data.  The final item in any array or dictionary should **NOT** have a trailing comma.

## INDI Debugging
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "DEBUG" : {
            "on"  : ["ENABLE"],
            "off" : ["DISABLE"]
        },
        "DEBUG_LEVEL" : {
            "on"  : ["DBG_ERROR", "DBG_WARNING", "DBG_SESSION", "DBG_DEBUG"],
            "off" : ["DBG_EXTRA_1"]
        },
        "LOGGING_LEVEL" : {
            "on"  : ["LOG_ERROR", "LOG_WARNING", "LOG_SESSION", "LOG_DEBUG"],
            "off" : ["LOG_EXTRA_1"]
        },
        "LOG_OUTPUT" : {
            "on"  : ["CLIENT_DEBUG", "FILE_DEBUG"],
            "off" : []
        }
    }
}
```
# ZWO
## ZWO 16-bit mode
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "CCD_VIDEO_FORMAT" : {
            "on"  : ["ASI_IMG_RAW16"],
            "off" : ["ASI_IMG_RAW8"]
        }
    }
}
```
## ZWO Offset
```json
{
    "PROPERTIES" : {
        "CCD_CONTROLS" : {
            "Offset" : 10
        }
    },
    "SWITCHES" : {}
}
```

## ZWO USB Bandwidth
```json
{
    "PROPERTIES" : {
        "CCD_CONTROLS" : {
            "BandWidth" : 40
        }
    },
    "SWITCHES" : {}
}
```
## Fix ASI120 black bands
* https://bbs.zwoastro.com/d/11923-firmware-bug-asi120mm-mini

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

# Svbony
## Svbony sv305 16-bit mode (INDI 2.0.4)
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "CCD_CAPTURE_FORMAT" : {
            "on"  : ["SVB_IMG_RAW16"],
            "off" : ["SVB_IMG_RAW8"]
        }
    }
}
```

## Svbony sv305 16-bit mode (INDI 2.0.3)
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "CCD_CAPTURE_FORMAT" : {
            "on"  : ["FORMAT_RAW16"],
            "off" : ["FORMAT_RAW8"]
        }
    }
}
```

## Svbony sv305 16-bit mode (old)
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "FRAME_FORMAT" : {
            "on"  : ["FORMAT_RAW12"],
            "off" : ["FORMAT_RAW8"]
        }
    }
}
```

# PlayerOne Astronomy
## PlayerOne 16-bit mode
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "CCD_VIDEO_FORMAT" : {
            "on"  : ["POA_RAW16"],
            "off" : ["POA_RAW8"]
        }
    }
}
```
## PlayerOne Offset
```json
{
    "PROPERTIES" : {
        "CCD_CONTROLS" : {
            "Offset" : 80
        }
    },
    "SWITCHES" : {}
}
```
## PlayerOne USB Bandwidth
```json
{
    "PROPERTIES" : {
        "CCD_CONTROLS" : {
            "USBBandWidthLimit" : 35
        }
    },
    "SWITCHES" : {}
}
```

# Touptek

## Touptek High Conversion Gain mode (new)
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "TC_CONVERSION_GAIN": {
            "on": [
                "GAIN_HIGH"
            ],
            "off": [
                "GAIN_LOW"
            ]
        }
    }
}
```

## Touptek High Conversion Gain mode (old)
```json
{
    "PROPERTIES" : {
        "TC_HGC_SET" : {
            "HCG Threshold" : 900,
            "HCG/LCG gain ratio" : 4.5
        }
    },
    "SWITCHES" : {
        "TC_HCG_CONTROL" : {
            "on"  : ["GAIN_HIGH"],
            "off" : ["GAIN_LOW", "GAIN_HDR"]
        }
    }
}
```

## Touptek & Altair raw mode
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


### IUC26000KPA

#### Night (HCG)
```json
{
    "PROPERTIES": {
        "CCD_CONTROLS": {
            "Speed": 9
        }
    },
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "6224 x 4168"
            ]
        },
        "TC_CONVERSION_GAIN": {
            "on": [
                "GAIN_HIGH"
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

#### Day (LCG)
```json
{
    "PROPERTIES": {
        "CCD_CONTROLS": {
            "Speed": 9
        }
    },
    "SWITCHES": {
        "CCD_RESOLUTION": {
            "on": [
                "6224 x 4168"
            ]
        },
        "TC_CONVERSION_GAIN": {
            "on": [
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

## Altair Hypercam 178C
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
## Altair 290C resolution
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

## Altair 224C resolution
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
## Altair Offset
```json
{
    "PROPERTIES" : {
        "CCD_OFFSET" : {
            "OFFSET" : 10
        }
    },
    "SWITCHES" : {}
}
```

# QHY
## QHY Offset
```json
{
    "PROPERTIES" : {
        "CCD_OFFSET" : {
            "OFFSET" : 10
        }
    },
    "SWITCHES" : {}
}
```

# indi_libcamera_ccd
## Disable AWB
```json
{
    "PROPERTIES" : {
        "Adjustments": {
            "AwbRed" : 1.0,
            "AwbBlue" : 1.0
        }
    },
    "SWITCHES": {}
}
```

## Enable JPEG mode
```json
{
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": ["JPG"],
            "off": ["DNG"]
        }
    },
    "PROPERTIES": {},
    "TEXT": {}
}
```

## Multiple cameras
If you have multiple MIPI CSI connected cameras, each will be presented as different cameras in the indi connection.  You will need to manually specify the camera name in the `CAMERA_NAME` field if you want a specific camera.  Otherwise, indi-allsky just picks the first camera it detects (which might be random).

For example:
* `LibCamera imx477-0`
* `LibCamera imx708-1`

# indi_pylibcamera
## Enable AWB
```json
{
    "SWITCHES": {
        "CAMCTRL_AWBENABLE": {
            "on": [
                "INDI_ENABLED"
            ],
            "off": []
        }
    },
    "PROPERTIES": {},
    "TEXT": {}
}
```


# Alpaca
```json
{
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "RAW_16"
            ]
        }
    },
    "PROPERTIES": {
        "DEVICE_NUMBER": {
            "DEVICE_NUMBER": 0
        }
    },
    "TEXT": {
        "SERVER_ADDRESS": {
            "HOST": "192.168.1.60",
            "PORT": "11111"
        }
    }
}
```


# DSLR
## Canon resolution and RAW mode

**Please ensure your camera is set to Manual/Bulb mode**

```json
{
    "PROPERTIES" : {
        "CCD_INFO" : {
            "CCD_MAX_X" : 5184,
            "CCD_MAX_Y" : 3456,
            "CCD_PIXEL_SIZE" : 4.3,
            "CCD_PIXEL_SIZE_X" : 4.3,
            "CCD_PIXEL_SIZE_Y" : 4.3,
            "CCD_BITSPERPIXEL" : 16
        }
    },
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "FORMAT_9"
            ]
        },
        "aperture": {
            "on": [
                "aperture0"
            ]
        }
    }
}
```
The capture format should set the camera to RAW mode.  See `./misc/camera_properties.py` to determine the correct FORMAT for your model.
* Canon 1300D: `FORMAT_9`
* Canon 450D: `FORMAT_7`
* Canon 5D: `FORMAT_7`
* Canon 600D: `FORMAT_9`
* Canon 60D: `FORMAT_8`
* Canon 6D: `FORMAT_8`

The aperture settings specific to your lens are discoverable via the `./misc/camera_properties.py` script.  The f-stop will likely need to be reduced for daytime operation.  `aperture0` should be wide open.


## CCD cooling
indi-allsky has native support for controlling temperature, however, you can still control the rate of temperature change
```json
{
    "PROPERTIES" : {
        "CCD_TEMP_RAMP" : {
            "RAMP_SLOPE"     : 5,
            "RAMP_THRESHOLD" : 0.5
        }
    },
    "SWITCHES" : {}
}
```

# Webcam
## indi_webcam_ccd resolution
```json
{
    "PROPERTIES" : {},
    "SWITCHES" : {
        "CAPTURE_VIDEO_SIZE" : {
            "on" : ["1280x720"]
        }
    }
}
```

## indi_v4l2_ccd resolution
```json
{
    "PROPERTIES": {},
    "SWITCHES": {
        "V4L2_SIZE_DISCRETE": {
            "on": ["1920x1080"]
        }
    }
}
```

## Webcam - IP Camera - Reolink
_Note: It is not recommended to use indi_webcam_ccd to download images from an IP Webcam.  Please use the pyCurl Camera instead._

```json
{
    "PROPERTIES": {},
    "TEXT": {
        "ONLINE_PATH": {
            "URL_PATH": "https://10.11.12.13/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=abcdefg123456789&user=username&password=password"
        }
    },
    "SWITCHES": {
        "CAPTURE_DEVICE": {
            "on": ["IP Camera"]
        },
        "ONLINE_PROTOCOL": {
            "on": ["HTTP"],
            "off": ["CUSTOM"]
        }
    }
}
```

# Simulator
## CCD Simulator - color, custom config
```json
{
    "PROPERTIES": {
        "SCOPE_INFO": {
            "FOCAL_LENGTH": 45,
            "APERTURE": 45
        },
        "CCD_OFFSET": {
            "OFFSET": 10
        },
        "SIMULATOR_SETTINGS": {
            "SIM_XRES": 1920,
            "SIM_YRES": 1080,
            "SIM_XSIZE": 2.4,
            "SIM_YSIZE": 2.4,
            "SIM_SATURATION": 9.0,
            "SIM_SKYGLOW": 11.0,
            "SIM_ROTATION": 90.0
        }
    },
    "SWITCHES": {
        "SIMULATE_BAYER": {
            "on": [
                "INDI_ENABLED"
            ],
            "off": [
                "INDI_DISABLED"
            ]
        }
    }
}
```