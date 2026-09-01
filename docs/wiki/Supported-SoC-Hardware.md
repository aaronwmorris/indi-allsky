# Tested Hardware
| Board               | Manufacturer            | CPU           | Distributions    | Notes |
| ------------------- | ----------------------- | ------------- | ---------------- | ----- |
| Raspberry Pi 4      | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 10 & 11<br />Ubuntu Mate (20.04) | 32 and 64 bit modes work |
| Raspberry Pi 3      | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 10      | |
| Raspberry Pi Zero   | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 10      | 512MB RAM is sufficient to support image capture.  Not enough ram to build videos with ffmpeg. |
| Rock 3A             | Radxa                   | Rockchip ARM  | Ubuntu 20.04     | |
| AML-S905X-CC (Le Potato) | Libre Computer     | Amlogic ARM   | Armbian 22.02    | I had issues with some of the USB ports not working for cameras. |
| Orange Pi Zero 2    | OrangePi                | Allwinner ARM | Armbian 22.05    | |
| Orange Pi PC Plus   | OrangePi                | Allwinner ARM | Armbian 22.05    | Required 2GB swapfile to build all python modules |

* Note:  My previous notes about PlayerOne Astronomy was likely just due to a driver problem (regardless of the SoC).  https://github.com/indilib/indi-3rdparty/issues/591

# DO NOT BUY
* Geniatech SoCs
    * The hardware looks decent, but the boards appear to have Android installed to the eMMC and it is extremely difficult to get the boards to boot to the TF Card slot.