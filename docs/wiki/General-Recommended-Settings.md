# Recommended Baseline Configuration

These guidelines represent operational recommendations for allsky camera installations.

---

## 1. Camera & Image Processing

1. **Capture Mode**: Configure the camera in 16-bit RAW format (RAW16 / Mono16) if supported by the hardware and INDI driver. RAW capture delivers greater dynamic range for nocturnal stretching compared to 8-bit JPEG/RGB24 modes.
   * See [Custom INDI Configuration](INDI-custom-config).
2. **Color Balance (SCNR)**: Enable Selective Color Noise Reduction (SCNR) in the Image tab to neutralize excess green cast typical of Bayer matrix sensors under light-polluted night skies.
3. **Histogram Stretching**:
   * **Standard Deviation Cutoff**: Set cutoff between `2.0` and `2.5` (default: `2.25`) for balanced night contrast without blowing out horizon light domes.
   * **Midtone Transfer Function (MTF)**: Shadow cutoff around `0.03`.
4. **Calibration**: Generate master dark frames to eliminate sensor thermal noise and hot pixels. See [Dark Calibration Frames](Dark-Calibration-Frames).
5. **Optical Masking**: Use the Image Circle Mask to conceal sensor margins and optical vignetting outside the lens projection circle. (Note: Image Circle Mask controls under the Processing tab require **Expert Mode** to be enabled in the configuration header).
6. **Processing Previews**: Utilize the interactive Image Processor utility (**Tools** → **Image Processor**) to test debayering, curves, and stretching on historical FITS or RAW frames without affecting live capture.

---

## 2. Enclosure & Host Hardware (Raspberry Pi & SBCs)

* **Thermal Management**: Install an active heatsink and cooling fan on the SBC processor. Continuous image compression and stacking generate substantial thermal load.
* **Optical Reflections**: Extinguish onboard status and activity LEDs. Internal LED flashing reflects off optical dome acrylic and creates artifacts on captured frames. See [Disable LEDs](Disable-LEDs).
* **Automated Recovery**: Enable the hardware watchdog timer so the system recovers autonomously from unattended system freezes. See [Hardware Watchdog Integration](Raspberry-Pi-Watchdog).
* **Dew Prevention**: Install a dew heater element (typically 1–2 Watts) surrounding the optical dome flange. See [Dew Heater Control](Dew-Heater-Support).
* **Network Connectivity**: Prefer a wired Ethernet connection over Wi-Fi. Power over Ethernet (PoE) provides combined power delivery and network stability.
* **Wi-Fi Power Management**: If Wi-Fi is mandatory, disable 802.11 power saving (**Tools** → **Network**) to prevent intermittent packet drops and SSH latency.
* **Raspberry Pi 5 Power Delivery**: Utilize an official 5V / 5A (27W) USB-C power supply or 802.3at PoE+ (30W). Standard 15W PoE or 5V / 3A power bricks can cause peripheral USB disconnects under camera load.

---

## 3. Related Hardware Guides

* [Raspberry Pi HQ Camera (IMX477)](Raspberry-PI-HQ-Camera)
* [Known Camera Issues Matrix](Known-Camera-Problems)
* [Disk Optimizations](Disk-Optimizations)
* [Memory Optimizations](Memory-Optimizations)