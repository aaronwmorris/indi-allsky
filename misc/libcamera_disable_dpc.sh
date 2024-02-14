#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


DPC_STRENGTH="0"

### libcamera Defective Pixel Correction (DPC) Strength
# https://datasheets.raspberrypi.com/camera/raspberry-pi-camera-guide.pdf
#
# 0 = Off
# 1 = Normal correction (default)
# 2 = Strong correction
###


LIBCAMERA_PREFIX="/usr"


echo
echo "#########################################################"
echo "### Welcome to the indi-allsky script to disable      ###"
echo "### Defective Pixel Correction (DPC)                  ###"
echo "#########################################################"
echo
echo
echo


if [[ -f "/usr/local/bin/libcamera-still" || -f "/usr/local/bin/rpicam-still" ]]; then
    LIBCAMERA_PREFIX="/usr/local"

    echo "Detected a custom installation of libcamera in /usr/local"
    echo
    echo
    sleep 3
fi


if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
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
    imx477_af
    imx219
    imx219_noir
    imx519
    imx708
    imx708_noir
    imx708_wide
    imx708_wide_noir
    arducam_64mp
"

for LIBCAMERA_JSON in $LIBCAMERA_CAMERAS; do
    ### PI4 and older
    JSON_FILE_VC4="${LIBCAMERA_PREFIX}/share/libcamera/ipa/rpi/vc4/${LIBCAMERA_JSON}.json"

    ### PI5
    JSON_FILE_PISP="${LIBCAMERA_PREFIX}/share/libcamera/ipa/rpi/pisp/${LIBCAMERA_JSON}.json"


    if [ -f "$JSON_FILE_VC4" ]; then
        echo "Disabling dpc in $JSON_FILE_VC4"

        TMP_DPC_JSON_VC4=$(mktemp --suffix=.json)
        jq --argjson rpidpc_strength "$DPC_STRENGTH" '."rpi.dpc".strength = $rpidpc_strength' "$JSON_FILE_VC4" > "$TMP_DPC_JSON_VC4"
        sudo cp -f "$TMP_DPC_JSON_VC4" "$JSON_FILE_VC4"
        sudo chown root:root "$JSON_FILE_VC4"
        sudo chmod 644 "$JSON_FILE_VC4"
        [[ -f "$TMP_DPC_JSON_VC4" ]] && rm -f "$TMP_DPC_JSON_VC4"
    else
        echo "File not found: $JSON_FILE_VC4"
    fi


    if [ -f "$JSON_FILE_PISP" ]; then
        echo "Disabling dpc in $JSON_FILE_PISP"

        TMP_DPC_JSON_PISP=$(mktemp --suffix=.json)
        jq --argjson rpidpc_strength "$DPC_STRENGTH" '."rpi.dpc".strength = $rpidpc_strength' "$JSON_FILE_PISP" > "$TMP_DPC_JSON_PISP"
        sudo cp -f "$TMP_DPC_JSON_PISP" "$JSON_FILE_PISP"
        sudo chown root:root "$JSON_FILE_PISP"
        sudo chmod 644 "$JSON_FILE_PISP"
        [[ -f "$TMP_DPC_JSON_PISP" ]] && rm -f "$TMP_DPC_JSON_PISP"
    else
        echo "File not found: $JSON_FILE_PISP"
    fi


done

