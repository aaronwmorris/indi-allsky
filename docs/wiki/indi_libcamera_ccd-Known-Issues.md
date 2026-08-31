# Overview
The `indi_libcamera_ccd` driver is a new INDI-native camera server which support libcamera CSI/MIPI cameras on Raspberry Pi.  The server works well, but is currently beta-quality.


## Issues as of Oct 2025
- Minimum gain is 1 not 0.  Using gain 0 causes the camera to misbehave (exposures take longer than normal to complete, etc)
    - (Just a note) Maximum analogue gain is 22.62 for the IMX477.  Different sensors have different max values, most others are 16.0.  Going higher than this introduces Digital Gain.  Other camera vendors permit Digital Gain as gain values increase (such as ZWO, Touptek, etc), so this is not specifically a "problem".
- Minimum exposure is reported as 0.0 which can cause problems with really short exposures.  A more appropriate minimum exposure should be manually defined.  ie `0.000032`
- Gain FITS header not populated (there may be other headers missing)
- Offset not reported.  This is called the "black level" in libcamera.  Example:  When running in DNG/RAW mode most cameras have an offset (black level) of 4096 (seriously!).
- When libcamera AWB (auto-white balance) is enabled, it  would be helpful to have the Red and Blue gains reported as FITS headers.
- ColorGains properties (`AWB Red` and `AWB Blue`) limited to 2.0 maximum.  Camera properties report 32.0 (float) is the real maximum.
- Focus not supported on cameras that have auto-focus.  Cameras that have auto-focus may be stuck with auto-focus enabled by default.


## Recommendations
- Set daytime gain to `1.0` (not 0 as allowed by the driver)
- Set night/moon mode gain no higher than `22.62`
- Disable libcamera AWB


```json
{
    "PROPERTIES" : {
        "Adjustments": {
            "AwbRed" : 1.0,
            "AwbBlue" : 1.0
        }
    },
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": ["DNG"],
            "off": ["JPG"]
        }
    }
}
```


## Links

https://github.com/indilib/indi-3rdparty/issues/1105