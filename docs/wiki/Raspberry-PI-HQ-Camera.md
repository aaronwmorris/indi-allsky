## Recommended settings
1. Use DNG RAW mode
1. Use `16-22.26` gain at night
1. Max exposure should be `30-60`s.  The HQ Camera is less sensitive than dedicated astronomy cameras and needs additional exposure time to compensate.
1. Disable libcamera Auto-White Balance [AWB] at night
    * libcamera performs AWB by taking multiple (up to 5) exposures at a given level to calculate the proper white balance.  This means a 60 second exposure can take up to 300 seconds (5 minutes!) to complete.  A significant amount of time is lost between exposures.
    * The libcamera AWB is very good at correcting the color balance, therefore disabling AWB will require additional settings to try to achieve similar results.
1. Enable SCNR - Average Neutral
    * When you enable RAW [DNG] mode, the data is RAW sensor data where no processing has been applied.
    * Modern color image sensors have a color bayer matrix with two green pixels for every red and blue which will result in a overall green bias in the image.
    * The SCNR algorithm creates a synthetic green channel and does a decent job at removing the green bias.
1. Set gamma correction between `1.5` and `2.0`
1. Stretching
    * Standard Deviation Cutoff with cutoff of `2.25`
    * or Midtone Transer Function [MTF] - Shadow cutoff `0.03`
1. [Optional] - Set Camera Bit depth
    * 12 or 16 may be the correct value depending on the version of libcamera
    * DNG RAW mode only
    * The automatic bit depth detection sometimes goes haywire and will detect the wrong bit depth which will result in a dark or completely gray image.

### JPEG mode
If you elect to use JPEG mode with AWB disabled, an additional configuration will be necessary.
1.  Disable Color Correction Matrix [CCM]
    * A bug was recently discovered in libcamera that incorrectly applies the CCM to images when AWB is disabled.  The CCM assumes a proper white balance is in place to properly color calibration.
        * https://github.com/raspberrypi/rpicam-apps/issues/784
        * https://github.com/aaronwmorris/indi-allsky/issues/1888
    * When SCNR is applied to the RPi HQ Camera jpeg images (with AWB disabled) the resulting image will have a blue bias.
    * As of Sept 2025, rpicam-apps 1.9.0 includes a new flag to disable CCM on the command line and this option is available in indi-allsky.
    * [Legacy] Instructions below
    

## DPC "Star Eater" Algorithm

Defective Pixel Correction [DPC] is enabled by default on the Raspberry PI HQ camera (IMX477).  Disabling the DPC requires 2 changes

1. Disable DPC in the imx477 kernel module (and reboot)

       echo "options imx477 dpc_enable=0" | sudo tee /etc/modprobe.d/imx477.conf

1. Disable DPC in tuning file
    * Raspberry Pi 5

          jq 'walk(if type == "object" and has ("rpi.dpc") then (.["rpi.dpc"].strength = 0) else . end)' /usr/share/libcamera/ipa/rpi/pisp/imx477.json > /etc/indi-allsky/imx477_no_dpc.json

    * Raspberry Pi 4/3

          jq 'walk(if type == "object" and has ("rpi.dpc") then (.["rpi.dpc"].strength = 0) else . end)' /usr/share/libcamera/ipa/rpi/vc4/imx477.json > /etc/indi-allsky/imx477_no_dpc.json

    * Add `--tuning-file /etc/indi-allsky/imx477_no_dpc.json` to libcamera options


### Legacy DPC instructions

DPC can be disabled with the following command on older Raspbian systems

```
sudo vcdbg set imx477_dpc 0
```

## Disable CCM
Add `--tuning-file /etc/indi-allsky/imx477_no_ccm.json` to the libcamera options after you use the jq command to disable CCM options in the custom tuning file.

### Raspberry Pi 5
```
jq 'walk(if type == "object" and has ("rpi.ccm") then (.["x.rpi.ccm"] = .["rpi.ccm"] | del(.["rpi.ccm"])) else . end)' /usr/share/libcamera/ipa/rpi/pisp/imx477.json > /etc/indi-allsky/imx477_no_ccm.json
```

### Raspberry Pi 4/3
```
jq 'walk(if type == "object" and has ("rpi.ccm") then (.["x.rpi.ccm"] = .["rpi.ccm"] | del(.["rpi.ccm"])) else . end)' /usr/share/libcamera/ipa/rpi/vc4/imx477.json > /etc/indi-allsky/imx477_no_ccm.json
```