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


I2C_BUS="1"
DS1307_I2C="0x68"


echo
echo "#######################################################"
echo "### Welcome to the indi-allsky i2c RTC setup script ###"
echo "#######################################################"

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run this script as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo
echo
echo "This script sets up an i2c RTC module"
echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo
echo "Default i2c bus:     i2c-${I2C_BUS}"
echo "Default rtc address: $DS1307_I2C"
echo
echo


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


echo "**** Installing packages... ****"
if [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "12" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "12" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "11" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "10" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "24.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "22.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "20.04" ]]; then
    sudo apt-get update
    sudo apt-get -y install \
        i2c-tools

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


# find script directory for service setup
#SCRIPT_DIR=$(dirname "$0")
#cd "$SCRIPT_DIR/.."
#ALLSKY_DIRECTORY=$PWD
#cd "$OLDPWD"


echo "**** Enable Raspberry Pi i2c interface ****"
sudo raspi-config nonint do_i2c 0


echo "**** Display i2c devices ****"
sudo i2cdetect -y "$I2C_BUS"


echo "**** Mask fake-hwclock service ****"
sudo systemctl mask fake-hwclock || true


echo "**** Setup rtc ****"
if [ -d "/sys/class/i2c-adapter/i2c-${I2C_BUS}" ]; then
    echo ds1307 "$DS1307_I2C" | sudo tee /sys/class/i2c-adapter/i2c-${I2C_BUS}/new_device || true
else
    echo "Error: i2c bus not found"
    exit 1
fi


echo "**** Setup enable RTC cronjob at /etc/cron.d/enable_i2c_rtc ****"
echo "@reboot root echo ds1307 $DS1307_I2C > /sys/class/i2c-adapter/i2c-${I2C_BUS}/new_device" | sudo tee /etc/cron.d/enable_i2c_rtc
sudo chown root:root /etc/cron.d/enable_i2c_rtc
sudo chmod 644 /etc/cron.d/enable_i2c_rtc



echo
echo
echo "RTC is now setup... enjoy"
echo
echo

