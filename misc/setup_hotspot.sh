#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset

PATH=/bin:/usr/bin
export PATH


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

# get primary group
PGRP=$(id -ng)


echo
echo "*** THIS SCRIPT DOES NOT FULLY FUNCTION YET ***"
echo
sleep 5


echo "#######################################################"
echo "### Welcome to the indi-allsky hotspot setup script ###"
echo "#######################################################"

echo
echo
echo "This script sets up a hotspot based on the astroberry astroberry-server-hotspot repository"
echo
echo

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run setup.sh as root"
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


echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        git \
        network-manager \
        cmake

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        git \
        network-manager \
        cmake

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        git \
        network-manager \
        cmake

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        git \
        network-manager \
        cmake

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


TMP_DIR=$(mktemp -d)
echo "Created temp dir $TMP_DIR"

cd "$TMP_DIR"
git clone https://github.com/rkaczorek/astroberry-server-hotspot.git
cd astroberry-server-hotspot
cmake CMakeLists.txt

sudo make install

cd $OLDPWD

echo
echo
echo "Please reboot for the hotspot changes to take effect"
echo
echo


# Cleanup
[[ -d "${TMP_DIR}" ]] && rm -fR "${TMP_DIR}"

