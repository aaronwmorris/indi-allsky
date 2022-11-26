#!/bin/bash

set -o errexit
set -o nounset
shopt -s nullglob

PATH=/usr/bin:/bin
export PATH


if [ -f "/usr/local/bin/indiserver" ]; then
    INDI_DRIVER_PATH="/usr/local/bin"
else
    INDI_DRIVER_PATH="/usr/bin"
fi


# get list of drivers
INDI_DRIVERS=()
cd "$INDI_DRIVER_PATH"
for I in indi_*_ccd indi_rpicam*; do
    INDI_DRIVERS[${#INDI_DRIVERS[@]}]="$I $I OFF"
done
cd "$OLDPWD"

#echo ${INDI_DRIVERS[@]}


CCD_DRIVER=""
while [ -z "$CCD_DRIVER" ]; do
    # shellcheck disable=SC2068
    CCD_DRIVER=$(whiptail --title "Camera Driver" --notags --nocancel --radiolist "Press space to select" 0 0 0 ${INDI_DRIVERS[@]} 3>&1 1>&2 2>&3)
done
echo "$CCD_DRIVER"


