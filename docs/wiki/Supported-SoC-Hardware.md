# Supported Hardware & Platforms

`indi-allsky` operates on 64-bit Linux architectures (`arm64` and `amd64`). The platform requires sufficient memory and CPU throughput to manage image capture loops, live debayering, star detection algorithms, and video compression pipelines.

---

## 1. Hardware Support Matrix

| Platform / Board | Manufacturer | Architecture | Recommended Operating Systems | Operational Notes |
|---|---|---|---|---|
| **Raspberry Pi 5** | Raspberry Pi Foundation | `arm64` (BCM2712) | Raspberry Pi OS 12 / 13 (64-bit), Ubuntu 24.04+ | **Recommended**. High I/O performance; PCIe NVMe boot supported via M.2 HAT. |
| **Raspberry Pi 4** | Raspberry Pi Foundation | `arm64` (BCM2711) | Raspberry Pi OS 12 / 13 (64-bit), Debian 12 / 13 | **Recommended**. Models with 2 GB, 4 GB, or 8 GB RAM perform reliably. |
| **Raspberry Pi 3 Model B/B+** | Raspberry Pi Foundation | `arm64` (BCM2837) | Raspberry Pi OS 12 / 13 (64-bit) | Functional for basic image capture. Long timelapse rendering times; 64-bit OS required. |
| **Raspberry Pi Zero 2 W** | Raspberry Pi Foundation | `arm64` (BCM2710A1) | Raspberry Pi OS 12 / 13 (64-bit) | 512 MB RAM supports image capture; requires physical swap for ffmpeg video encoding. |
| **x86_64 Mini PCs** (Intel N100, N95, N150, Celeron, AMD Ryzen) | Various | `amd64` | Debian 12 / 13, Ubuntu 24.04 / 26.04 | **Recommended for multi-camera & high-res**. Superior CPU throughput for fast stacking and 4K timelapses. |
| **Radxa Rock 3A / 5B** | Radxa | `arm64` (Rockchip) | Debian 12, Ubuntu 22.04+ | High hardware performance; verify USB controller stability with high-bandwidth cameras. |
| **Libre Computer Le Potato** (AML-S905X-CC) | Libre Computer | `arm64` (Amlogic) | Armbian, Debian 12 | 2 GB model recommended; some USB ports share bandwidth limitations. |
| **Orange Pi Zero 2 / PC Plus** | OrangePi | `arm64` (Allwinner) | Armbian | Requires minimum 2 GB swapfile if compiling packages from source. |

---

## 2. Unsupported Platforms

* **32-bit Architectures (`armhf`, `armv7l`, `i386`)**:
  * **Raspberry Pi Zero (v1)** and **Raspberry Pi 1 / 2 (32-bit)** are completely unsupported. Modern scientific Python dependencies (`pyarrow`, `scipy`, `dask-image`) do not distribute pre-compiled 32-bit wheels.
* **Geniatech / Android-Locked TV Boxes**:
  * Hardware with non-standard bootloaders or locked eMMC partitions that resist native Linux kernel initialization.

---

## 3. Storage Recommendations

* **High-Endurance MicroSD / eMMC**: Standard consumer SD cards degrade rapidly under continuous 24/7 image writes. Utilize SanDisk High Endurance, Samsung PRO Endurance, or industrial-grade eMMC modules.
* **NVMe / SSD Boot**: For Raspberry Pi 5 (via PCIe HAT) or Mini PCs, booting from NVMe or SATA SSD eliminates storage bottlenecks and prevents flash wear.
* **Mount Options**: Ensure partitions are mounted with `noatime` to reduce write overhead. See [Disk Optimizations](Disk-Optimizations).
