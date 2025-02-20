#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


### Non-interactive options example ###
#export INDIALLSKY_INDI_VERSION=2.0.3
###


#### config ####
INDI_VERSION="${INDIALLSKY_INDI_VERSION:-}"
#### end config ####


PYINDI_2_0_4="git+https://github.com/indilib/pyindi-client.git@d8ad88f#egg=pyindi-client"
PYINDI_2_0_0="git+https://github.com/indilib/pyindi-client.git@674706f#egg=pyindi-client"
PYINDI_1_9_9="git+https://github.com/indilib/pyindi-client.git@ce808b7#egg=pyindi-client"
PYINDI_1_9_8="git+https://github.com/indilib/pyindi-client.git@ffd939b#egg=pyindi-client"


#INDI_DRIVER_PATH="/usr/bin"

if [[ "$(id -u)" == "0" ]]; then
    echo
    echo "Please do not run $(basename "$0") as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
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

if [ -f "/usr/local/bin/indiserver" ]; then
    #INDI_DRIVER_PATH="/usr/local/bin"

    echo
    echo "Detected a custom installation of INDI in /usr/local/bin"
    echo
fi


echo
echo
echo "The purpose of this script is to rebuild pyindi-client against"
echo " newer indilib packages."
echo
echo "Rebuild proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# pyindi-client setup
SUPPORTED_INDI_VERSIONS=(
    "2.1.2.1"
    "2.1.2"
    "2.1.1"
    "2.1.0"
    "2.0.9"
    "2.0.8"
    "2.0.7"
    "2.0.6"
    "2.0.5"
    "2.0.4"
    "2.0.3"
    "2.0.2"
    "2.0.1"
    "2.0.0"
    "1.9.9"
    "1.9.8"
    "1.9.7"
    "skip"
)


# try to detect installed indiversion
#DETECTED_INDIVERSION=$(${INDI_DRIVER_PATH}/indiserver --help 2>&1 | grep -i "INDI Library" | awk "{print \$3}")
DETECTED_INDIVERSION=$(pkg-config --modversion libindi)
echo
echo
echo "Detected INDI version: $DETECTED_INDIVERSION"
sleep 5

INDI_VERSIONS=()
for v in "${SUPPORTED_INDI_VERSIONS[@]}"; do
    if [ "$v" == "$DETECTED_INDIVERSION" ]; then
        # allow the version to be selected
        INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v ON"

        #INDI_VERSION=$v
        #break
    else
        INDI_VERSIONS[${#INDI_VERSIONS[@]}]="$v $v OFF"
    fi
done


while [ -z "${INDI_VERSION:-}" ]; do
    # shellcheck disable=SC2068
    INDI_VERSION=$(whiptail --title "Installed INDI Version for pyindi-client" --nocancel --notags --radiolist "Press space to select" 0 0 0 ${INDI_VERSIONS[@]} 3>&1 1>&2 2>&3)
done

echo
echo "Selected: $INDI_VERSION"
sleep 3



START_TIME=$(date +%s)


# shellcheck source=/dev/null
source "${ALLSKY_DIRECTORY}/virtualenv/indi-allsky/bin/activate"


if [ "$INDI_VERSION" == "2.0.3" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.2" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.1" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "2.0.0" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_2_0_0"
elif [ "$INDI_VERSION" == "1.9.9" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_1_9_9"
elif [ "$INDI_VERSION" == "1.9.8" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_1_9_8"
elif [ "$INDI_VERSION" == "1.9.7" ]; then
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_1_9_8"
else
    # default latest release
    pip3 uninstall -y pyindi-client
    pip3 install --no-cache-dir --upgrade "$PYINDI_2_0_4"
fi



END_TIME=$(date +%s)

echo
echo
echo "Completed in $((END_TIME - START_TIME))s"
echo
