#!/bin/bash


#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


DPC_STRENGTH="1"

### libcamera Defective Pixel Correction (DPC) Strength
# https://datasheets.raspberrypi.com/camera/raspberry-pi-camera-guide.pdf
#
# 0 = Off
# 1 = Normal correction (default)
# 2 = Strong correction
###



echo
echo "#########################################################"
echo "### Welcome to the indi-allsky script to restore      ###"
echo "### Defective Pixel Correction (DPC)                  ###"
echo "#########################################################"
echo
echo
echo



if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename $0) as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


LIBCAMERA_CAMERAS="
    imx290
    imx378
    imx477
    imx477_noir
    imx519
"

for LIBCAMERA_JSON in $LIBCAMERA_CAMERAS; do
    JSON_FILE="/usr/share/libcamera/ipa/raspberrypi/${LIBCAMERA_JSON}.json"

    if [ -f "$JSON_FILE" ]; then
        echo "Disabling dpc in $JSON_FILE"

        TMP_JSON=$(mktemp)
        jq --argjson rpidpc_strength "$DPC_STRENGTH" '."rpi.dpc".strength = $rpidpc_strength' "$JSON_FILE" > $TMP_JSON
        sudo cp -f "$TMP_JSON" "$JSON_FILE"
        sudo chown root:root "$JSON_FILE"
        sudo chmod 644 "$JSON_FILE"
        [[ -f "$TMP_JSON" ]] && rm -f "$TMP_JSON"
    else
        echo "File not found: $JSON_FILE"
    fi
done



