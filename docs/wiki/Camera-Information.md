indi-allsky works on a wide variety of cameras across several vendors.  Picking the correct gain values is critical to getting the maximum performance of your camera.

| Camera     | Vendor     | Resolution  | Dimensions    | Diagonal | Max Analog Gain (dB) | Bits    | Pixels | CFA  |
| ---------- | ---------- | ----------- | ------------- | -------- | -------------------- | ------- | ------ | ---- |
| IMX708 (CM3) | RPi      | 4608 x 2592 | 6.45 x 3.63   | 7.40     | 16.0             |         | 1.4    | BGGR |
| IMX477     | RPi        | 4056 x 3040 | 6.29 x 4.71   | 7.86     | 22.26            | 12      | 1.55   | BGGR |
| IMX378     | Waveshare  | 4056 x 3040 | 6.29 x 471    | 7.86     | 22.26            | 12      | 1.55   | BGGR |
| 64mp Hawkeye |          | 9152 x 6944 | 7.32 x 5.56   | 9.19     |                  |         | 0.8    | RGGB |
| IMX519     |            | 4656 x 3496 | 5.68 x 4.27   | 7.11     |                  |         | 1.22   | RGGB |
| ov5647 (CM1) |          | 2592 x 1944 | 3.63 x 2.72   | 4.54     |                  |         | 1.4    | BGGR |
| IMX219 (CM2) |          | 3280 x 2464 | 3.67 x 2.76   | 4.59     |                  |         | 1.12   | BGGR |
| IMX296 (gs)  | RPi      | 1456 x 1088 | 5.02 x 3.75   | 6.27     |                  |         | 3.45   | mono |
| IMX178     |            | 3096 x 2080 |               |          | 24.0  ?          | 14      | 2.4    |      |
| IMX678     |            | 3840 x 2160 |               |          | 30.0              | 12      | 2.0    | RGGB |
| IMX715     |            | 3864 x 2192 |               |          |                  | 12      | 1.45   |      |
| IMX662     |            | 1920 x 1080 |               |          |                  |         | 2.9    |      |
| IMX432     |            | 1608 x 1104 |               |          |                  |         | 9.0    | mono |
| IMX462     |            | 1920 x 1080 | 5.57 x 3.13   | 6.39     |                  |         | 2.9    | RGGB |
| IMX290     |            | 1936 x 1096 | 5.57 x 3.13   | 6.39     | 30.0             |         | 2.9    | GRBG |
| IMX482     |            | 1920 x 1080 |               |          |                  |         | 5.8    | RGGB |
| IMX485     |            | 3840 x 2160 |               |          |                  | 12      | 2.9    |      |
| IMX585     |            | 3856 x 2180 |               |          |                  | 12      | 2.9    |      |
| ASI120MC-S | ZWO        | 1280 x 960  | 4.80 x 3.60   | 6.00     | No info          | 12      | 3.75   | GRBG |
| ASI220MM   |            | 1920 x 1080 |               |          |                  | 12      | 4.0    | mono |
| IMX224     |            | 1304 x 976  |               |          |                  | 12      | 3.75   |      |
| IMX385     |            | 1936 x 1096 | 7.26 x 4.11   | 8.34     | 30.0              | 12      | 3.75   | RGGB |
| IMX183     |            | 5472 x 3648 | 13.13 x 8.76  | 15.78    | 27.0 ?            | 12      | 2.4    | RGGB |
| IMX533     |            | 3008 x 3008 |               |          |                  | 14      | 3.76   |      |
| IMX174     |            | 1936 x 1216 |               |          |                  |         | 5.86   | mono |
| SV305 (imx290) | Svbony     | 1920 x 1080 |            |          | No info          | 12     | 2.9    | GRBG |
| QHY5LII    | QHY        | 1280 x 960  |            |          | No info          | 12      | 3.75   |      |
| Mars C (imx462) | Player One | 1944 x 1096 |            |          | No info          | 12    | 2.9    | RGGB |
| T7C        | Daytson    | 1280 x 960  |            |          | No info          | 12      | 3.75   | GRBG |


# libcamera

## imx477
```
0 : imx477 [4056x3040 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx477@1a)
    Modes: 'SRGGB10_CSI2P' : 1332x990 [120.05 fps - (696, 528)/2664x1980 crop]
           'SRGGB12_CSI2P' : 2028x1080 [50.03 fps - (0, 440)/4056x2160 crop]
                             2028x1520 [40.01 fps - (0, 0)/4056x3040 crop]
                             4056x3040 [10.00 fps - (0, 0)/4056x3040 crop]

    Available controls for 4056x3040 SRGGB12_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..22.260870]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [114..694422939]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [100000..694434742]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/4056x3040]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

## imx378
Reports as imx477

```
0 : imx477 [4056x3040 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx477@1a)
    Modes: 'SRGGB10_CSI2P' : 1332x990 [120.05 fps - (696, 528)/2664x1980 crop]
           'SRGGB12_CSI2P' : 2028x1080 [50.03 fps - (0, 440)/4056x2160 crop]
                             2028x1520 [40.01 fps - (0, 0)/4056x3040 crop]
                             4056x3040 [10.00 fps - (0, 0)/4056x3040 crop]

    Available controls for 4056x3040 SRGGB12_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..22.260870]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [114..694422939]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [100000..694434742]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/4056x3040]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

## imx708
Arducam module

```
0 : imx708 [4608x2592 10-bit RGGB] (/base/axi/pcie@1000120000/rp1/i2c@88000/imx708@1a)
    Modes: 'SRGGB10_CSI2P' : 1536x864 [120.13 fps - (768, 432)/3072x1728 crop]
                             2304x1296 [56.03 fps - (0, 0)/4608x2592 crop]
                             4608x2592 [14.35 fps - (0, 0)/4608x2592 crop]

    Available controls for 4608x2592 SRGGB10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AfMetering : [0..1]
    AfMode : [0..2]
    AfPause : [0..2]
    AfRange : [0..2]
    AfSpeed : [0..1]
    AfTrigger : [0..1]
    AfWindows : [(0, 0)/0x0..(65535, 65535)/65535x65535]
    AnalogueGain : [1.122807..16.000000]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [26..220416802]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [69669..220535845]
    HdrMode : [0..4]
    LensPosition : [0.000000..15.000000]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/51x39..(0, 0)/4608x2592]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```


## imx462
### imx290 overlay
```
0 : imx462 [1920x1080 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx290@1a)
    Modes: 'SRGGB10_CSI2P' : 1280x720 [60.00 fps - (320, 180)/1280x720 crop]
                             1920x1080 [60.00 fps - (0, 0)/1920x1080 crop]
           'SRGGB12_CSI2P' : 1280x720 [60.00 fps - (320, 180)/1280x720 crop]
                             1920x1080 [60.00 fps - (0, 0)/1920x1080 crop]

    Available controls for 1920x1080 SRGGB10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..29.512093]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [14..115686258]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [16666..115687148]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/1920x1080]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

### arducam-pivariety overlay
```
0 : arducam-pivariety [1920x1080 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/arducam_pivariety@c)
    Modes: 'SRGGB10_CSI2P' : 1920x1080 [60.00 fps - (0, 0)/1920x1080 crop]

    Available controls for 1920x1080 SRGGB10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..200.000000]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [14..15534385]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [16666..15534444]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/1920x1080]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

## imx519
Arducam module

```
0 : imx519 [4656x3496 10-bit RGGB] (/base/axi/pcie@1000120000/rp1/i2c@88000/imx519@1a)
    Modes: 'SRGGB10_CSI2P' : 1280x720 [80.01 fps - (1048, 1042)/2560x1440 crop]
                             1920x1080 [60.05 fps - (408, 674)/3840x2160 crop]
                             2328x1748 [30.00 fps - (0, 0)/4656x3496 crop]
                             3840x2160 [18.00 fps - (408, 672)/3840x2160 crop]
                             4656x3496 [9.00 fps - (0, 0)/4656x3496 crop]

    Available controls for 4656x3496 SRGGB10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AfMetering : [0..1]
    AfMode : [0..2]
    AfPause : [0..2]
    AfRange : [0..2]
    AfSpeed : [0..1]
    AfTrigger : [0..1]
    AfWindows : [(0, 0)/0x0..(65535, 65535)/65535x65535]
    AnalogueGain : [1.000000..16.000000]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [592..248567756]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [111092..248572499]
    HdrMode : [0..4]
    LensPosition : [0.000000..32.000000]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/51x39..(0, 0)/4656x3496]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```
## imx327

```
0 : imx327 [1920x1080 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx290@1a)
    Modes: 'SRGGB10_CSI2P' : 1280x720 [60.00 fps - (320, 180)/1280x720 crop]
                             1920x1080 [60.00 fps - (0, 0)/1920x1080 crop]
           'SRGGB12_CSI2P' : 1280x720 [60.00 fps - (320, 180)/1280x720 crop]
                             1920x1080 [60.00 fps - (0, 0)/1920x1080 crop]

    Available controls for 1920x1080 SRGGB10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..29.512093]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [14..115686258]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [16666..115687148]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/1920x1080]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

## imx335
Arducam module
```
0 : imx335 [2592x1944 12-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx335@1a)
Modes: 'SRGGB10_CSI2P' : 2592x1944 [29.99 fps - (0, 0)/2592x1944 crop]
'SRGGB12_CSI2P' : 2592x1944 [29.99 fps - (0, 0)/2592x1944 crop]
Available controls for 2592x1944 SRGGB10_CSI2P mode:
----------------------------------------------------
AeConstraintMode : [0..3]
AeEnable : [false..true]
AeExposureMode : [0..3]
AeFlickerMode : [0..1]
AeFlickerPeriod : [100..1000000]
AeMeteringMode : [0..3]
AnalogueGain : [1.000000..1000.000000]
AnalogueGainMode : [0..1]
AwbEnable : [false..true]
AwbMode : [0..7]
Brightness : [-1.000000..1.000000]
CnnEnableInputTensor : [false..true]
ColourCorrectionMatrix : [0.000000..8.000000]
ColourGains : [0.000000..32.000000]
ColourTemperature : [100..100000]
Contrast : [0.000000..32.000000]
ExposureTime : [7..1000190]
ExposureTimeMode : [0..1]
ExposureValue : [-8.000000..8.000000]
FrameDurationLimits : [33340..1000256]
HdrMode : [0..4]
NoiseReductionMode : [0..4]
Saturation : [0.000000..32.000000]
ScalerCrop : [(0, 0)/64x64..(0, 0)/2592x1944]
Sharpness : [0.000000..16.000000]
StatsOutputEnable : [false..true]
SyncFrames : [1..1000000]
SyncMode : [0..2]
```

## imx296 (gs)
```
0 : imx296 [1456x1088 10-bit MONO] (/base/soc/i2c0mux/i2c@1/imx296@1a)
    Modes: 'R10_CSI2P' : 1456x1088 [60.38 fps - (0, 0)/1456x1088 crop]

    Available controls for 1456x1088 R10_CSI2P mode:
    ------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AnalogueGain : [1.000000..251.188644]
    AnalogueGainMode : [0..1]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    Contrast : [0.000000..32.000000]
    ExposureTime : [29..15534385]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [16562..15534444]
    HdrMode : [0..4]
    NoiseReductionMode : [0..4]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/1456x1088]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```

## imx283
Found in allsky forums

```
Available controls:
    Sharpness : [0.000000..16.000000]
    AwbEnable : [false..true]
    Contrast : [0.000000..32.000000]
    Saturation : [0.000000..32.000000]
    Brightness : [-1.000000..1.000000]
    AeFlickerPeriod : [100..1000000]
    HdrMode : [0..4]
    ExposureValue : [-8.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    StatsOutputEnable : [false..true]
    ScalerCrop : [(0, 0)/337x228..(0, 0)/5472x3648]
    ExposureTime : [58..129373756]
    AeEnable : [false..true]
    NoiseReductionMode : [0..4]
    AeConstraintMode : [0..3]
    FrameDurationLimits : [55577..164960255]
    AnalogueGain : [1.000000..22.505495]
    AeFlickerMode : [0..1]
    AwbMode : [0..7]
    AeMeteringMode : [0..3]
    AeExposureMode : [0..3]
```

## ov64a40 (Owl sight)

```
0 : ov64a40 [9248x6944 10-bit] (/base/soc/i2c0mux/i2c@1/ov64a40@36)
    Modes: 'SBGGR10_CSI2P' : 1920x1080 [70.56 fps - (784, 1312)/7712x4352 crop]
                             2312x1736 [32.24 fps - (0, 0)/9280x6976 crop]
                             3840x2160 [19.40 fps - (784, 1312)/7712x4352 crop]
                             4624x3472 [9.86 fps - (0, 0)/9280x6976 crop]
                             8000x6000 [3.18 fps - (624, 472)/8048x6032 crop]
                             9248x6944 [2.60 fps - (0, 0)/9280x6976 crop]

    Available controls for 9248x6944 SBGGR10_CSI2P mode:
    ----------------------------------------------------
    AeConstraintMode : [0..3]
    AeEnable : [false..true]
    AeExposureMode : [0..3]
    AeFlickerMode : [0..1]
    AeFlickerPeriod : [100..1000000]
    AeMeteringMode : [0..3]
    AfMetering : [0..1]
    AfMode : [0..2]
    AfPause : [0..2]
    AfRange : [0..2]
    AfSpeed : [0..1]
    AfTrigger : [0..1]
    AfWindows : [(0, 0)/0x0..(65535, 65535)/65535x65535]
    AnalogueGain : [1.000000..15.992188]
    AnalogueGainMode : [0..1]
    AwbEnable : [false..true]
    AwbMode : [0..7]
    Brightness : [-1.000000..1.000000]
    CnnEnableInputTensor : [false..true]
    ColourCorrectionMatrix : [0.000000..8.000000]
    ColourGains : [0.000000..32.000000]
    ColourTemperature : [100..100000]
    Contrast : [0.000000..32.000000]
    ExposureTime : [868..910889189]
    ExposureTimeMode : [0..1]
    ExposureValue : [-8.000000..8.000000]
    FrameDurationLimits : [383962..910890926]
    HdrMode : [0..4]
    LensPosition : [0.000000..15.000000]
    NoiseReductionMode : [0..4]
    Saturation : [0.000000..32.000000]
    ScalerCrop : [(0, 0)/64x64..(0, 0)/9280x6976]
    Sharpness : [0.000000..16.000000]
    StatsOutputEnable : [false..true]
    SyncFrames : [1..1000000]
    SyncMode : [0..2]
```