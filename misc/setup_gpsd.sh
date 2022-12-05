#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

GPS_SERIAL_PORT="/dev/ttyACM0"


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
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo
echo
echo "Serial port: $GPS_SERIAL_PORT"
echo
echo


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        gpsd \
        gpsd-tools \
        gpsd-clients

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
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
 -e 's|^[^#]\?\(DEVICES=.*\)|#\1|i' \
 /etc/default/gpsd > "$TMP_DEV"


echo "DEVICES=\"$GPS_SERIAL_PORT\"" >> "$TMP_DEV"


sudo cp -f "$TMP_DEV" /etc/default/gpsd
sudo chown root:root /etc/default/gpsd
sudo chmod 644 /etc/default/gpsd
[[ -f "$TMP_DEV" ]] && rm -f "$TMP_DEV"



sudo systemctl enable gpsd
sudo systemctl restart gpsd




echo
echo
echo "GPSD is now installed... enjoy"
echo
echo

