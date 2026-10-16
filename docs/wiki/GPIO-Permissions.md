# Overview

> [!NOTE]
> **Debian Package (`.deb`) Installations**: The package installer automatically configures hardware group memberships (`gpio`, `dialout`, `i2c`, `spi`) and policy permissions for the `indi-allsky` service account. You do **not** need to create custom udev rules or manually install GPIO packages. This guide is only relevant for non-package manual installations on platforms with non-standard GPIO permissions.

Some single board computers do not permit non-root access to GPIO pins.  Allowing non-root access requires a udev rule.

## udev rule

```bash
sudo tee /etc/udev/rules.d/99-gpio.rules <<EOF
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="dialout", MODE="0660", TAG+="uaccess"
EOF

```

Reboot!