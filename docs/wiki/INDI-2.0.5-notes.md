# ZWO ASI GPSStartLine bug

The ASI SDK 1.31/1.32 introduces some new paramters for some cameras.  The default setting for one of the new settings is incompatible which causes the camera to be unable to change gain and take exposures.

```
indi.newMessage(): new Message 2023-12-14T08:45:40: Error: Invalid range for GPSStartLine (GPSStartLine). Valid range is from 0 to 975. Requested value is 53248

indi.newMessage() #344: new Message 2023-12-29T16:28:57: Error: Invalid range for GPSEndLine (GPSEndLine). Valid range is from 0 to 2079. Requested value is 16648
```

The following settings will correct the issue
```json
{
    "PROPERTIES" : {
        "CCD_CONTROLS" : {
            "GPSStartLine" : 0,
            "GPSEndLine"   : 0
        }
    },
    "SWITCHES" : {}
}
```

This bug affects the following cameras:
* ASI224
* ASI178
* ASI385
* ASI1600
* ?

## Related
* https://github.com/indilib/indi-3rdparty/issues/867