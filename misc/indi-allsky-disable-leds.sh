#!/bin/bash
##########################################
# Script to disable GPIO controlled LEDs #
##########################################


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
    if [ -e "/sys/class/leds/$LED/brightness" ]; then
        echo "Turning off LED: $LED"
        echo 0 > "/sys/class/leds/$LED/brightness"
    fi
done
