#!/bin/bash
##########################################
# Script to disable GPIO controlled LEDs #
##########################################


### Add the following to /boot/firmware/config.txt to disable ethernet LEDs
#dtparam=eth_led0=4
#dtparam=eth_led1=4


### LEDs discovered
# * Raspberry Pi
# * Libre Computer Le Potato
# * RockPi


LEDS="
    ACT
    PWR
    led1
    led0
    green\:status
    red\:power
    librecomputer\:blue
    librecomputer\:system-status
    status
"

echo "Disabling system LEDs"

for LED in $LEDS; do
    if [ -e "/sys/class/leds/$LED/trigger" ]; then
        echo "Turning off LED: $LED"
        echo none > "/sys/class/leds/$LED/trigger"
    elif [ -e "/sys/class/leds/$LED/brightness" ]; then
        # old method
        echo "Turning off LED: $LED"
        echo 0 > "/sys/class/leds/$LED/brightness"
    fi
done
