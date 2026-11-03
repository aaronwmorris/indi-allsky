# General
These instructions are mainly for Raspberry PI hardware.  If your hardware has 4GB of memory, decreasing swappiness is probably the only useful optimization.  All of the optimizations are recommended for 1GB systems.

## Automatic Hardware Profiling & Configuration Presets

During installation and initial configuration bootstrapping (`indi-allsky-ctl reset-config`), `indi-allsky` dynamically evaluates host physical memory, active swap space, and CPU cores to apply hardware-optimized defaults that prevent Out-Of-Memory (OOM) terminations and excessive load out of the box:

| Hardware Tier | Memory Boundary | FFmpeg Scaling (`FFMPEG_VFSCALE`) | Queue Size (`IMAGE_QUEUE_MAX`) | Upload Workers |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1 (Constrained)** | $< 1.5\text{ GB RAM}$ | `-2:720` (720p HD) | 3 | 1 |
| **Tier 2 (Moderate)** | $1.5\text{ GB} \le \text{RAM} < 3.5\text{ GB}$ | `-2:1080` (1080p FHD) | 5 | 1 |
| **Tier 3 (Standard)** | $3.5\text{ GB} \le \text{RAM} < 6.0\text{ GB}$ | `-2:1440` (1440p QHD) | 8 | 2 |
| **Tier 4 (High Performance)** | $\ge 6.0\text{ GB RAM}$ | `""` (Native Resolution) | 10 | 3 |

Inspect your host's assigned tier and recommended preset values via CLI:
```bash
indi-allsky-ctl profile
```


## Decrease swappiness
This will decrease the rate at which the Linux kernel will swap out memory pages to the swap file and reduce disk I/O.
```bash
echo "vm.swappiness = 1" | sudo tee /etc/sysctl.d/90-indi-allsky.conf

sudo sysctl --system
```

### Armbian swappiness
The swappiness setting may have to be commented out in ```/etc/sysctl.conf```

## Increase Swap space

### Trixie
* Edit `/etc/rpi/swap.conf`
```
[Main]
Mechanism=swapfile

[File]
FixedSizeMiB=2048
```

### Bookworm
* Edit `/etc/dphys-swapfile`
* Set `CONF_SWAPSIZE=512` to increase to 512MB
```bash
sudo dphys-swapfile swapoff
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Armbian swap
* /etc/default/armbian-zram-config

## Decrease video ram
* sudo raspi-config
    * 4 Performance Options -> P2 GPU Memory
    * Set memory to 16MB
        * Note: libcamera requires at least 32MB GPU memory for imx477 and imx378
* Reboot

## Disable GUI
```bash
sudo systemctl set-default multi-user.target

reboot
``` 
