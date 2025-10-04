#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION_ID="${VERSION_ID:-unknown}"
CPU_ARCH=$(uname -m)


echo
echo "#######################################################"
echo "### Welcome to the indi-allsky LED disable script   ###"
echo "#######################################################"


if [ -f "/proc/device-tree/model" ]; then
    SYSTEM_MODEL=$(tr -c '[:print:]' ' ' </proc/device-tree/model)
else
    echo
    echo "ERROR: LED disable function not supported on this system"
    exit 1
fi


echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo
echo "System: $SYSTEM_MODEL"
echo
echo

echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


if echo "$SYSTEM_MODEL" | grep -i "raspberry" >/dev/null 2>&1; then
    if [ ! -f "/boot/firmware/config.txt" ]; then
        echo
        echo "ERROR: /boot/firmware/config.txt not found"
        exit 1
    fi


    TMP_CONFIG=$(mktemp)

    # remove original lines
    sed \
     -e '/^[^#]\?dtparam=pwr_led_trigger=.*$/d' \
     -e '/^[^#]\?dtparam=pwr_led_activelow=.*$/d' \
     -e '/^[^#]\?dtparam=act_led_trigger=.*$/d' \
     -e '/^[^#]\?dtparam=act_led_activelow=.*$/d' \
     -e '/^[^#]\?dtparam=eth_led0=.*$/d' \
     -e '/^[^#]\?dtparam=eth_led1=.*$/d' \
     /boot/firmware/config.txt > "$TMP_CONFIG"


    # Power LED
    # shellcheck disable=SC2129
    echo "dtparam=pwr_led_trigger=none" >> "$TMP_CONFIG"
    echo "dtparam=pwr_led_activelow=on" >> "$TMP_CONFIG"


    # Activity LED
    echo "dtparam=act_led_trigger=none" >> "$TMP_CONFIG"
    echo "dtparam=act_led_activelow=off" >> "$TMP_CONFIG"


    # Ethernet LEDs
    echo "dtparam=eth_led0=4" >> "$TMP_CONFIG"
    echo "dtparam=eth_led1=4" >> "$TMP_CONFIG"


    sudo cp -f "$TMP_CONFIG" "/boot/firmware/config.txt"
    sudo chown root:root "/boot/firmware/config.txt"
    sudo chmod 644 "/boot/firmware/config.txt"


    echo
    echo
    echo "LEDs should be disabled at next boot"
else
    echo
    echo "ERROR: LED disable function not supported"
    exit 1
fi
