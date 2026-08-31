# Modules
| Module             | Sensor   | Rating | Notes |
| ------------------ | -------- | ------ | ----- |
| Camera Module v1   | ov5647   | C      | Max exposure: 6s or 1s |
| Camera Module v2   | imx219   | C      | Max exposure: 11s or 1.2s |
| HQ Camera          | imx477   | A      |      |
| Camera Module v3   | imx708   | A      |      |
| imx378             | imx378   | A      | Virtually identical to imx477 |
| imx519             | imx519   | A      |      |
| HawkEye 64MP       | imx682   | B      | Processing RAW/DNG bin1 data is slow on SBCs.  RAW frames are 122MB. |
| OwlSight 64MP      | ov64a40  | B      | Exposure is not linear in bin 2 and 4 |
| imx290             | imx290   |        | Untested |
| imx462             | imx462   | A      | Very sensitive to noise in higher gains (+16) |
| imx327             | imx327   | A      | Very sensitive to noise in higher gains (+16) |
| GS Camera Module   | imx296   | A      |      |
| imx335             | imx335   | D      | Max exposure: 1s |


## Instructions
Please read the instructions on the Waveshare site
* IMX477 - https://www.waveshare.com/wiki/IMX477_12.3MP_Camera
* IMX378 - https://www.waveshare.com/wiki/IMX378-190_12.3MP_Camera
* IMX519 - https://www.waveshare.com/wiki/IMX519-78_16MP_AF_Camera
* 64mp HawkEye - https://www.arducam.com/64mp-ultra-high-res-camera-raspberry-pi/
* 64mp OwlSight - https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/64MP-OV64A40/
* IMX462 - https://www.waveshare.com/wiki/IMX462_2MP_Starlight_Camera


## Manual instructions
Camera auto-detection may not detect the camera.  You may need to manual load the overlay for your camera.

### IMX477
Add to `/boot/firmware/config.txt`
```
dtoverlay=imx477
#dtoverlay=imx477,cam0
# imx477 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### IMX378
Add to `/boot/firmware/config.txt`
```
dtoverlay=imx378,cam0
# imx378 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### IMX708
Add to `/boot/firmware/config.txt`
```
dtoverlay=imx708,cam0
# imx708 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### IMX462
Add to `/boot/firmware/config.txt`
```
camera_auto_detect=0

dtoverlay=imx462,cam0,clock-frequency=74250000
# imx462 requires minimum 32MB of GPU memory
#gpu_mem=32
```

#### IMX462 Legacy
Some imx462 cameras need to use the imx290 overlay.
```
camera_auto_detect=0

dtoverlay=imx290,cam0,clock-frequency=74250000
# imx462 requires minimum 32MB of GPU memory
#gpu_mem=32
```

#### Arducam IMX462
```
camera_auto_detect=0

dtoverlay=arducam-pivariety
#gpu_mem=32
```

### IMX327
Add to `/boot/firmware/config.txt`
```
camera_auto_detect=0

dtoverlay=imx327,clock-frequency=74250000
# imx327 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### IMX519
Add to `/boot/firmware/config.txt`
```
camera_auto_detect=0

dtoverlay=imx519,cam0
# imx519 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### IMX296 (Global Shutter)
```
camera_auto_detect=0

dtoverlay=imx296,cam0
# imx296 requires minimum 32MB of GPU memory
#gpu_mem=32
```

### 64mp HawkEye
```
# requires arducam software
camera_auto_detect=0

dtoverlay=arducam-64mp
gpu_mem=128
```

### 64mp OwlSight
```
camera_auto_detect=0
#dtoverlay=vc4-kms-v3d,cma-512


dtoverlay=ov64a40,cam0
#gpu_mem=128
```

```
# The overlay will not load automatically for me
sudo dtoverlay ov64a40
```

#### Low Speed
* There is likely no difference between low and high speeds in an all sky system

```
camera_auto_detect=0

dtoverlay=ov64a40,link-frequency=360000000
#gpu_mem=128
```

#### High Speed (default)
```
camera_auto_detect=0

dtoverlay=ov64a40,link-frequency=456000000
#gpu_mem=128
```

# Customizations
The command used to generate images with libcamera-still may be customized.

https://www.raspberrypi.com/documentation/computers/camera_software.html

## High Conversion Gain [HCG]
Recent Linux kernels have added support for manually toggling the HCG of cameras that support this feature.  IMX290, IMX462, and IMX327 (maybe)

```
echo "Y" | sudo tee /sys/module/imx290/parameters/hcg_mode
```

## Focusing
Focusing will only work with camera modules with auto-focuser capability like the camera module 3
```
--autofocus-mode manual --lens-position 3.1
```

### Focus Notes
* A value of `3.0` should focus the ceiling inside a room
* `0.0` should be "infinity" which is the default

### Definition
```
Moves the lens to a fixed focal distance, normally given in dioptres (units of 1 / distance in metres).

    0.0 will move the lens to the "infinity" position

    Any other number: move the lens to the 1 / number position, so the value 2 would focus at approximately 0.5m

    default - move the lens to a default position which corresponds to the hyperfocal position of the lens.
```

## Binning
### IMX477 and IMX378
Bin2 mode (half resolution).  This is useful with SoCs with lower memory resources like Raspberry Pi 3.
```
--mode 2028:1520
```

Bin4 mode
```
--mode 1014:760

# cropped
--mode 1332:990:10
```

### Alternate tuning file
July 2023 update.  The location of the tuning files has changed.

#### Raspberry Pi 5
```
--tuning-file /usr/share/libcamera/ipa/rpi/pisp/imx477.json
```

#### Raspberry Pi 3-4, Zero
```
--tuning-file /usr/share/libcamera/ipa/rpi/vc4/imx477.json
```

Old location
```
--tuning-file /usr/share/libcamera/ipa/raspberrypi/imx477.json
```

#### Manual size adjustment
--width and --height only change the output image size in software, but it does not change the sensor parameters.
```
--width 2028 --height 1520
```

### 64mp Hawk-eye
Bin2 (16mp)
```
--mode 4624:3472
```

Bin4 (4mp)
```
--mode 2312:1736
```

## Streaming video
### tcp
* Raspberry Pi

      rpicam-vid --timeout 0 --inline --nopreview --camera 0 --gain 16 --framerate 15 --listen --codec h264 -o tcp://0.0.0.0:8000

    * Note:  Needs `rpicam-apps` package

* Client

      cvlc tcp/h264://raspberrypi.local:8000

### RTSP
* Raspberry Pi

      rpicam-vid --timeout 0 --inline --nopreview --camera 0 --gain 16 --framerate 15 --codec h264 -o - | cvlc -vv stream:///dev/stdin --sout '#rtp{sdp=rtsp://:8554/stream}' :demux=h264

    * Note:  Needs `rpicam-apps` package

* Client

      ffplay rtsp://raspberrypi.local:8554/stream

    * Note: I could got get VLC to open the RTSP stream
