# Overview

Some single board computers do not permit non-root access to GPIO pins.  Allowing non-root access requires a udev rule.

## udev rule

```bash
sudo tee /etc/udev/rules.d/99-gpio.rules <<EOF
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="dialout", MODE="0660", TAG+="uaccess"
EOF

```

Reboot!