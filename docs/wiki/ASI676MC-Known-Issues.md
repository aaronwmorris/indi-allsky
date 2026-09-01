# Overview
The ASI676MC is known to return occasional "purple" images.


## Purple Images
https://github.com/aaronwmorris/indi-allsky/issues/2007

I suspect the camera is occasionally returning a bayered image with the wrong bayer offset which means a different bayer pattern would need to be used for the correct color output.

The issue appears to be exacerbated while running in RAW16 mode.  Switching to RGB24 reduces the occurrence of purple images.

```json
{
    "SWITCHES": {
        "CCD_VIDEO_FORMAT": {
            "on": [
                "ASI_IMG_RGB24"
            ],
            "off": [
                "ASI_IMG_RAW16"
            ]
        }
    },
    "PROPERTIES": {},
    "TEXT": {}
}
```  

