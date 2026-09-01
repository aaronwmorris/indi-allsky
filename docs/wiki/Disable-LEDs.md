# Automatic setup

The indi-allsky repository contains a script to automatically perform the correct action to disable the systems LEDs:

```
./misc/setup_disable_leds.sh
```

# Manual instructions
## Raspberry Pi
Add the following parameters to `/boot/firmware/config.txt`

### Raspberry Pi 5
```
# Disable the PWR LED
dtparam=power_led_trigger=none
dtparam=power_led_activelow=off

# Disable the Activity LED
dtparam=act_led_trigger=none
dtparam=act_led_activelow=off

# Disable ethernet port LEDs
dtparam=eth_led0=4
dtparam=eth_led1=4
```

### Raspberry Pi 4/3
```
# Disable the PWR LED
dtparam=pwr_led_trigger=none
dtparam=pwr_led_activelow=on

# Disable the Activity LED
dtparam=act_led_trigger=none
dtparam=act_led_activelow=off

# Disable ethernet port LEDs
dtparam=eth_led0=4
dtparam=eth_led1=4
```

### Legacy Raspberry Pi
Create a script in `/usr/local/bin`

/usr/local/bin/disable_leds.sh
```bash
sudo tee /usr/local/bin/disable_leds.sh <<EOF
#!/bin/bash

# New names
echo 0 > /sys/class/leds/ACT/brightness
echo 0 > /sys/class/leds/PWR/brightness

# Old names
echo 0 > /sys/class/leds/led1/brightness
echo 0 > /sys/class/leds/led0/brightness
EOF

```

Make script executable
```bash
sudo chmod 755 /usr/local/bin/disable_leds.sh
```

Add script to crontab
```bash
sudo tee /etc/cron.d/disable_leds <<EOF
@reboot root /usr/local/bin/disable_leds.sh >/dev/null 2>&1
EOF

```

## Orange Pi
```bash
sudo tee /usr/local/bin/disable_leds.sh <<EOF
#!/bin/bash

echo 0 > /sys/class/leds/green\:status/brightness
echo 0 > /sys/class/leds/red\:power/brightness
EOF

```

## AML-S905X-CC (Le Potato)
```bash
sudo tee /usr/local/bin/disable_leds.sh <<EOF
#!/bin/bash

echo 0 > /sys/class/leds/librecomputer\:blue/brightness
echo 0 > /sys/class/leds/librecomputer\:system-status/brightness
EOF

```
* Note: The red power LED cannot be disabled in software.

## RockPi

```bash
sudo tee /usr/local/bin/disable_leds.sh <<EOF
#!/bin/bash

echo 0 > /sys/class/leds/status/brightness
EOF

```
Note: The green power LED cannot be disabled in software.