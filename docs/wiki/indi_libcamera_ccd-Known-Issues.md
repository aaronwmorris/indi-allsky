# `indi_libcamera_ccd` Known Issues & Driver Tuning

The `indi_libcamera_ccd` driver is an INDI-native C++ driver interface for MIPI-CSI sensors managed by the Raspberry Pi libcamera subsystem (e.g., Raspberry Pi Camera Module 3, HQ Camera, Global Shutter Camera). While offering low latency and direct hardware integration, several driver-level anomalies require specific configuration adjustments.

---

## 1. Documented Driver Characteristics

* **Zero Gain Fault**: The driver permits setting gain to `0`, which can cause internal pipeline hangs or severe frame timeout errors. Minimum operational analog gain must be set to `1.0`.
* **Analog vs. Digital Gain Ceiling**:
  * Sony IMX477 (Raspberry Pi HQ Camera): Maximum analog gain is `22.62`.
  * Sony IMX708 (Camera Module 3) and IMX296 (Global Shutter): Maximum analog gain is `16.0`.
  * Setting gain values exceeding these ceilings engages digital gain, which amplifies sensor read noise and quantization error.
* **Minimum Exposure Reporting**: The driver may report `0.0` seconds as the minimum exposure value, causing auto-exposure division errors. Set the manual minimum daytime exposure limit to `0.000032` seconds.
* **Offset / Black Level Calibration**: In native 12-bit DNG/RAW streaming, libcamera imposes a fixed black level pedestal (often `4096` on 16-bit stretched buffers) that must be accounted for during bias/dark frame calibration.
* **Auto White Balance (AWB)**: Dynamic AWB changes color balance frame-to-frame, interfering with daytime timelapse consistency and star detection. AWB should be disabled in favor of static color gain multipliers.

---

## 2. Recommended Configuration Preset

Under **Camera Settings -> INDI Custom Properties / Switches**, apply the following overrides:

```json
{
    "PROPERTIES": {
        "Adjustments": {
            "AwbRed": 1.0,
            "AwbBlue": 1.0
        }
    },
    "SWITCHES": {
        "CCD_CAPTURE_FORMAT": {
            "on": [
                "DNG"
            ],
            "off": [
                "JPG"
            ]
        }
    }
}
```

### Exposure and Gain Limits
* **Daytime Min Gain**: `1.0`
* **Daytime Max Gain**: `1.0`
* **Daytime Min Exposure**: `0.000032`
* **Nighttime Max Gain**: `16.0` (or `22.62` for IMX477)

---

## 3. Upstream References

* Upstream development and bug tracker: [indilib/indi-3rdparty Issue #1105](https://github.com/indilib/indi-3rdparty/issues/1105)