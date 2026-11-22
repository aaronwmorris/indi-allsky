# Known Camera Issues & Workarounds

This page serves as a centralized reference for known hardware, firmware, and driver limitations across camera platforms supported by `indi-allsky`.

---

## Camera Issue Matrix

| Camera / Family | Primary Known Issue | Impact | Documentation & Resolution |
|---|---|---|---|
| **ZWO ASI120MC-S** | USB 3.0 packet drop / bus timeouts | Failed exposures, frame timeouts, bus freezes. | [ASI120MC-S Camera Issues](ASI120MC-S-Camera-Issues) — Force USB 2.0 port or limit USB bandwidth in driver settings. |
| **ZWO ASI676MC** | Hardware purple frame corruption in RAW16 | Occasional frames contain distorted purple horizontal stripes or corrupted Bayer matrices. | [ASI676MC Known Issues](ASI676MC-Known-Issues)<br>[Purple Frame Repair Technical Details](ASI676MC-Purple-Frame-Repair-Details) — Automated RAW16 pixel reconstruction or RGB24 capture mode. |
| **ZWO ASI224MC** | Intermittent purple frame distortion | Similar color artifacting to ASI676MC. | Use RGB24 mode workaround; the automated mathematical repair algorithm is tailored specifically to ASI676MC Bayer layout. |
| **Raspberry Pi HQ Camera (IMX477)** | GPU memory allocation & libcamera timeouts | Image capture fails on high resolution or long exposure night capture. | [Raspberry Pi HQ Camera](Raspberry-PI-HQ-Camera)<br>[libcamera Enablement](libcamera-enablement) — Allocate minimum 32 MB GPU RAM in `raspi-config`. |
| **ToupTek / Altair / Ogma / Omegon** | USB transfer timeouts on embedded Linux hosts | Capture thread hangs or drops frames under high transfer load. | [Touptek Known Issues](Touptek-Known-Issues) — Adjust USB transfer block size and buffer allocation. |
| **QHY (USB 3.0 Models)** | Distribution `fxload` tool lacks USB 3.0 firmware upload support | Camera firmware fails to load when connected to USB 3.0 ports. | [Build fxload for USB3 Support](Build-fxload-for-USB3-support) — Compile patched `fxload` binary to initialize camera Cypress FX3 USB controller. |
| **indi_libcamera_ccd Driver** | Driver-level exposure sync faults | Inconsistent exposure timing under legacy libcamera versions. | [indi_libcamera_ccd Known Issues](indi_libcamera_ccd-Known-Issues) — Use modern native libcamera interface or `indi_pylibcamera`. |