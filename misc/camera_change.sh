#!/bin/bash

echo
echo
echo "NOTICE: Script has been renamed"
echo
echo "Running indiserver_only_setup.sh"
echo
sleep 5


SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.." || catch_error
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD" || catch_error


"$ALLSKY_DIRECTORY/misc/indiserver_only_setup.sh"

