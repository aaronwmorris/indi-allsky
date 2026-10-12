# Tested Hardware
| Board               | Manufacturer            | CPU           | Distributions    | Notes |
| ------------------- | ----------------------- | ------------- | ---------------- | ----- |
| Raspberry Pi 5      | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 13 & 12 | 32 mode will not work |
| Raspberry Pi 4      | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 13 & 12 | 32 mode will not work |
| Raspberry Pi 3      | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 13 & 12 | 32 mode will not work |
| Raspberry Pi Zero 2 | Raspberry Pi Foundation | Broadcom ARM  | Raspbian 13 & 12 | 512MB RAM is sufficient to support image capture.  Not enough ram to build videos with ffmpeg. |
| Raspberry Pi Zero   | Raspberry Pi Foundation | Broadcom ARM  |                  | WILL NOT WORK - Only 32-bit |
| Rock 3A             | Radxa                   | Rockchip ARM  | Ubuntu 20.04     | |
| AML-S905X-CC (Le Potato) | Libre Computer     | Amlogic ARM   | Armbian 22.02    | I had issues with some of the USB ports not working for cameras. |
| Orange Pi Zero 2    | OrangePi                | Allwinner ARM | Armbian 22.05    | |
| Orange Pi PC Plus   | OrangePi                | Allwinner ARM | Armbian 22.05    | Required 2GB swapfile to build all python modules |

# DO NOT BUY
* Geniatech SoCs
    * The hardware looks decent, but the boards appear to have Android installed to the eMMC and it is extremely difficult to get the boards to boot to the TF Card slot.
