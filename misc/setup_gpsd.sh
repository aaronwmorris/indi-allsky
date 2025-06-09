#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


if [ ! -f "/etc/os-release" ]; then
    echo
    echo "Unable to determine OS from /etc/os-release"
    echo
    exit 1
fi

source /etc/os-release


DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION_ID="${VERSION_ID:-unknown}"
CPU_ARCH=$(uname -m)


if [ -n "${1-}" ]; then
    GPS_SERIAL_PORT="$1"
else
    GPS_SERIAL_PORT="/dev/ttyACM0"
fi


echo
echo "####################################################"
echo "### Welcome to the indi-allsky GPSD setup script ###"
echo "####################################################"

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run this script as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo
echo
echo "This script sets up GPSD"
echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo
echo
echo "Serial port: $GPS_SERIAL_PORT"
echo
echo


if [ ! -c "$GPS_SERIAL_PORT" ]; then
    echo "WARNING: $GPS_SERIAL_PORT is not a valid device"
    echo
    echo
fi


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


if [[ "$DISTRO_ID" == "debian" || "$DISTRO_ID" == "raspbian" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "13" ]]; then
        DISTRO="debian_13"
    elif [[ "$DISTRO_VERSION_ID" == "12" ]]; then
        DISTRO="debian_12"
    elif [[ "$DISTRO_VERSION_ID" == "11" ]]; then
        DISTRO="debian_11"
    elif [[ "$DISTRO_VERSION_ID" == "10" ]]; then
        DISTRO="debian_10"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "ubuntu" ]]; then
    if [[ "$DISTRO_VERSION_ID" == "24.04" ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" == "22.04" ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "20.04" ]]; then
        DISTRO="ubuntu_20.04"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

elif [[ "$DISTRO_ID" == "linuxmint" ]]; then
    if [[ "$DISTRO_VERSION_ID" =~ ^22 ]]; then
        DISTRO="ubuntu_24.04"
    elif [[ "$DISTRO_VERSION_ID" =~ ^21 ]]; then
        DISTRO="ubuntu_22.04"
    elif [[ "$DISTRO_VERSION_ID" == "6" ]]; then
        DISTRO="debian_12"
    else
        echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
        exit 1
    fi

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


echo "**** Installing packages... ****"
if [[ "$DISTRO" == "debian_13" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO" == "debian_12" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO" == "debian_11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO" == "debian_10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO" == "ubuntu_24.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-clients

elif [[ "$DISTRO" == "ubuntu_22.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-clients

elif [[ "$DISTRO" == "ubuntu_20.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        telnet \
        gpsd \
        gpsd-clients

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


# find script directory for service setup
#SCRIPT_DIR=$(dirname "$0")
#cd "$SCRIPT_DIR/.."
#ALLSKY_DIRECTORY=$PWD
#cd "$OLDPWD"



# Comment out the DEVICE directives
TMP_DEV=$(mktemp)
sed \
 -e 's|^[^#]\?\(GPSD_OPTIONS=.*\)|#\1|i' \
 -e 's|^[^#]\?\(DEVICES=.*\)|#\1|i' \
 /etc/default/gpsd > "$TMP_DEV"


echo "GPSD_OPTIONS=\"-n\"" >> "$TMP_DEV"
echo "DEVICES=\"$GPS_SERIAL_PORT\"" >> "$TMP_DEV"


sudo cp -f "$TMP_DEV" /etc/default/gpsd
sudo chown root:root /etc/default/gpsd
sudo chmod 644 /etc/default/gpsd
[[ -f "$TMP_DEV" ]] && rm -f "$TMP_DEV"



sudo systemctl enable gpsd
sudo systemctl restart gpsd



echo "**** Ensure user is a member of the dialout group ****"
# for GPS and serial port access
sudo usermod -a -G dialout "$USER"


# disable ModemManager
echo "*** Disable ModemManger ***"
if systemctl --quiet is-enabled "ModemManager.service" 2>/dev/null; then
    sudo systemctl stop ModemManager
    sudo systemctl disable ModemManager
fi


echo
echo
echo "Use \"cgps\" to test your GPS adapter"
echo
echo
echo "GPSD is now installed... enjoy"
echo
echo

