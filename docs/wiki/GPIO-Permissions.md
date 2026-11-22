# GPIO Hardware Permissions

Interfacing with hardware devices—such as dew heaters, cooling fans, stepper focusers, and relay switches—requires read and write access to GPIO character devices (`/dev/gpiochip*`). On many single-board computers (Raspberry Pi, Orange Pi, Rockchip, and Armbian-supported platforms), access is restricted to the `root` user by default.

---

## 1. Group Membership

Ensure the service user executing `indi-allsky` belongs to the appropriate device groups:

```bash
sudo usermod -aG dialout,gpio indi-allsky
```

---

## 2. Udev Rule Configuration

To grant persistent non-root read/write permissions across reboots, install a udev rule targeting the modern `gpiochip` character device subsystem:

```bash
sudo tee /etc/udev/rules.d/99-gpio.rules <<'EOF'
# Modern Linux gpiochip subsystem
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="dialout", MODE="0660", TAG+="uaccess"

# Legacy sysfs GPIO interface (if applicable)
SUBSYSTEM=="gpio", KERNEL=="gpio*", ACTION=="add", PROGRAM="/bin/sh -c 'chown -R root:dialout /sys/class/gpio && chmod -R 770 /sys/class/gpio'"
EOF
```

Apply the udev rules immediately without rebooting:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=gpio
```

---

## 3. Verification

Verify that the GPIO device nodes reflect the correct group permissions (`dialout` or `gpio` with read/write access):

```bash
ls -l /dev/gpiochip*
```

Expected output format:
```text
crw-rw---- 1 root dialout 254, 0 Oct 16 12:00 /dev/gpiochip0
crw-rw---- 1 root dialout 254, 1 Oct 16 12:00 /dev/gpiochip1
```

If `libgpiod-utils` is installed, enumerate detected GPIO chips and pin availability:
```bash
gpiodetect
gpioinfo
```