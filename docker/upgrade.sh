#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


echo "#############################################################"
echo "### Welcome to the indi-allsky docker code upgrade script ###"
echo "#############################################################"
echo
echo
echo
echo "This script rebuilds the containers that contain code when you"
echo "want to upgrade indi-allsky."
echo
echo "Please ensure you have pulled down the latest code from GitHub"
echo
echo "The expected run time is 60s or less if you still have your"
echo "build cache from previous builds"
echo
echo
echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


START_TIME=$(date +%s)


docker compose \
    build \
    capture.indi.allsky \
    gunicorn.indi.allsky \
    webserver.indi.allsky


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo

echo
echo "You may now restart your containers"
echo
echo "  docker compose restart capture.indi.allsky gunicorn.indi.allsky webserver.indi.allsky"
echo


echo
echo "Enjoy!"

