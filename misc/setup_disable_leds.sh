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
    SYSTEM_MODEL=$(cat /proc/device-tree/model)
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


    # Power LED
    if ! grep "^dtparam=pwr_led_trigger=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=pwr_led_trigger=none" | sudo tee -a /boot/firmware/config.txt
    fi

    if ! grep "^dtparam=pwr_led_activelow=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=pwr_led_activelow=off" | sudo tee -a /boot/firmware/config.txt
    fi


    # Activity LED
    if ! grep "^dtparam=act_led_trigger=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=act_led_trigger=none" | sudo tee -a /boot/firmware/config.txt
    fi

    if ! grep "^dtparam=act_led_activelow=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=act_led_activelow=off" | sudo tee -a /boot/firmware/config.txt
    fi


    # Ethernet LEDs
    if ! grep "^dtparam=eth_led0=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=eth_led0=4" | sudo tee -a /boot/firmware/config.txt
    fi
    if ! grep "^dtparam=eth_led1=" /boot/firmware/config.txt >/dev/null 2>&1; then
        echo "dtparam=eth_led1=4" | sudo tee -a /boot/firmware/config.txt
    fi

    echo
    echo
    echo "LEDs should be disabled at next boot"
else
    echo
    echo "ERROR: LED disable function not supported"
    exit 1
fi
