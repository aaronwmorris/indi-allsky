#!/bin/bash

PATH=/usr/bin:/bin
export PATH


if [ -f "/usr/local/bin/indiserver" ]; then
    INDISERVER="/usr/local/bin/indiserver"
else
    INDISERVER="/usr/bin/indiserver"
fi


"$INDISERVER" -v -p 7624 indi_simulator_telescope "$INDIALLSKY_CCD_DRIVER"

