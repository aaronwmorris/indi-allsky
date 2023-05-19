#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


if [ -f "/usr/local/bin/indiserver" ]; then
    INDISERVER="/usr/local/bin/indiserver"
else
    INDISERVER="/usr/bin/indiserver"
fi


if [ -n "${INDIALLSKY_INDI_GPS_DRIVER:-}" ]; then
    "$INDISERVER" \
        -v \
        -p 7624 \
        indi_simulator_telescope \
        "$INDIALLSKY_INDI_CCD_DRIVER" \
        "$INDIALLSKY_INDI_GPS_DRIVER"

else
    echo "No GPS driver configured"
    "$INDISERVER" \
        -v \
        -p 7624 \
        indi_simulator_telescope \
        "$INDIALLSKY_INDI_CCD_DRIVER"
fi

