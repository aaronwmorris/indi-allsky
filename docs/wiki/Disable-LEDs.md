# Disabling Onboard LEDs

Light pollution originating from host Single Board Computer (SBC) activity and power LEDs can cause internal reflections inside camera domes or enclosures. Disabling these indicators ensures optimal sensor dark-sky sensitivity.

---

## 1. Automated Configuration

The automated disable script interrogates `/proc/device-tree/model` and updates the firmware configuration (`/boot/firmware/config.txt`) on Raspberry Pi 3, 4, and 5 hardware.

### Debian Package (`.deb`) Installations
Execute via `indi-allsky-ctl`:
```bash
sudo indi-allsky-ctl disable-leds
```

### Source / Git (`setup.sh`) Installations
Execute the script directly from the repository root:
```bash
sudo ./misc/setup_disable_leds.sh
```

A system reboot is required for device tree parameter alterations to take effect:
```bash
sudo reboot
```

---

## 2. Manual Configuration

### Raspberry Pi 5
Append the following parameters to `/boot/firmware/config.txt`:

```ini
# Disable Power LED
dtparam=power_led_trigger=none
dtparam=power_led_activelow=off

# Disable Activity LED
dtparam=act_led_trigger=none
dtparam=act_led_activelow=off

# Disable Gigabit Ethernet Jack LEDs
dtparam=eth_led0=4
dtparam=eth_led1=4
```

### Raspberry Pi 4 and 3
Append the following parameters to `/boot/firmware/config.txt`:

```ini
# Disable Power LED
dtparam=pwr_led_trigger=none
dtparam=pwr_led_activelow=on

# Disable Activity LED
dtparam=act_led_trigger=none
dtparam=act_led_activelow=off

# Disable Ethernet Jack LEDs (Pi 4 only)
dtparam=eth_led0=4
dtparam=eth_led1=4
```

---

## 3. Runtime Sysfs LED Control (Other SBC Architectures)

For boards lacking device-tree overlay parameters, LEDs may be extinguished at boot time via sysfs triggers.

Create `/usr/local/bin/disable_leds.sh`:
```bash
sudo tee /usr/local/bin/disable_leds.sh <<'EOF'
#!/bin/bash
# Extinguish known LED sysfs nodes if present
for led in \
    /sys/class/leds/ACT \
    /sys/class/leds/PWR \
    /sys/class/leds/led0 \
    /sys/class/leds/led1 \
    /sys/class/leds/green:status \
    /sys/class/leds/red:power \
    /sys/class/leds/librecomputer:blue \
    /sys/class/leds/librecomputer:system-status \
    /sys/class/leds/status; do
    if [ -d "$led" ]; then
        echo none > "$led/trigger" 2>/dev/null || true
        echo 0 > "$led/brightness" 2>/dev/null || true
    fi
done
EOF
sudo chmod 755 /usr/local/bin/disable_leds.sh
```

Register a systemd service or cron entry to execute the script at startup:
```bash
sudo tee /etc/cron.d/disable_leds <<'EOF'
@reboot root /usr/local/bin/disable_leds.sh >/dev/null 2>&1
EOF
```

> [!NOTE]
> On certain hardware platforms—such as Libre Computer Le Potato (AML-S905X-CC) and Radxa RockPi—the hardware power indicator LED is hard-wired directly to the 5V power bus and cannot be disabled via software controls. Opaque physical shielding (e.g., electrical tape) is required for those diodes.