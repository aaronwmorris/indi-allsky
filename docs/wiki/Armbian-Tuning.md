# Armbian Performance & Memory Tuning

Armbian utilizes RAM-based filesystem optimizations (such as `armbian-ramlog`, `armbian-zram-config`, and a `tmpfs` mount on `/tmp`) by default to protect SD card endurance. On single-board computers with 1 GB or 2 GB of RAM, these mechanisms can exhaust physical memory during high-resolution RAW image processing, timelapse video encoding, or manual package compilation.

---

## 1. Disable or Expand `tmpfs` on `/tmp`

Compiling large modules or buffering extensive image stacks in `/tmp` will exhaust RAM if `/tmp` is mounted as an in-memory `tmpfs`:

1. Inspect `/etc/fstab`:
   ```bash
   sudo nano /etc/fstab
   ```
2. Locate any active `tmpfs` mount assigned to `/tmp`:
   ```text
   # Comment out the /tmp mount line:
   # tmpfs /tmp tmpfs defaults,nosuid 0 0
   ```
3. Alternatively, expand the `tmpfs` size limit or mount a physical disk path.

---

## 2. Adjust or Disable `armbian-ramlog`

`armbian-ramlog` stores system logs in RAM and syncs to disk periodically. If systemd journal logs grow rapidly due to camera driver debugging:

1. Edit the configuration:
   ```bash
   sudo nano /etc/default/armbian-ramlog
   ```
2. Disable the service or increase the allocated buffer:
   ```bash
   ENABLED=false
   ```

---

## 3. Physical Swap Configuration

ZRAM compresses memory in-place; under extreme memory pressure, compression CPU overhead competes with camera capture. For low-RAM SBCs, configure a dedicated physical swap file on eMMC, NVMe, or fast USB storage:

1. Disable Armbian default ZRAM swap:
   ```bash
   sudo nano /etc/default/armbian-zram-config
   # Set ENABLED=false
   ```
2. Install and configure `dphys-swapfile`:
   ```bash
   sudo apt-get install dphys-swapfile
   sudo nano /etc/dphys-swapfile
   # Configure CONF_SWAPSIZE=2048 (for 2GB swap)
   sudo systemctl restart dphys-swapfile
   ```

---

## 4. Kernel Virtual Memory Tuning

Reduce the kernel's aggressive tendency to swap active process memory:

```bash
echo "vm.swappiness = 1" | sudo tee /etc/sysctl.d/90-indi-allsky.conf
sudo sysctl --system
```

> [!NOTE]
> On Armbian systems, check `/etc/sysctl.conf` to ensure existing `vm.swappiness` overrides do not take precedence.