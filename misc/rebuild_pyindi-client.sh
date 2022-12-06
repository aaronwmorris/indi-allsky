#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "$VIRTUAL_ENV" ]]; then
    echo
    echo "Please do not run $(basename "$0") with a virtualenv active"
    echo "Run \"deactivate\" to exit your current virtualenv"
    echo
    echo
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"


if [ ! -d "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky" ]; then
    echo
    echo "indi-allsky virtualenv not found, please run setup.sh"
    echo
    echo
    exit 1
fi


echo
echo
echo "The purpose of this script is to rebuild pyindi-client against"
echo " newer indilib packages."
echo
echo "Rebuild proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10



INDI_VERSIONS=(
    "v1.9.9 v1.9.9 ON"
    "v1.9.8 v1.9.8 OFF"
    "v1.9.7 v1.9.7 OFF"
)


INDI_VERSION=""
while [ -z "$INDI_VERSION" ]; do
    # shellcheck disable=SC2068
    INDI_VERSION=$(whiptail --title "INDI Version" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_VERSIONS[@]} 3>&1 1>&2 2>&3)
done

echo "Selected: $INDI_VERSION"


if [ "$INDI_VERSION" == "v1.9.8" ]; then
    CLIENT_VERSION='git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client'
elif [ "$INDI_VERSION" == "v1.9.7" ]; then
    CLIENT_VERSION='git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client'
else
    # assuming 1.9.9 or newer
    CLIENT_VERSION='git+https://github.com/indilib/pyindi-client.git@ce808b7#egg=pyindi-client'
fi


START_TIME=$(date +%s)


# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"
pip3 uninstall -y pyindi-client
pip3 install --no-binary :all: --upgrade "$CLIENT_VERSION"


END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo
