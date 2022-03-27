#!/bin/bash

#set -x  # command tracing
set -o errexit
#set -o nounset


PATH=/bin:/usr/bin
export PATH


HOTSPOT_IP="10.42.0.1"
HOTSPOT_SSID="IndiAllsky"
HOTSPOT_PSK="indiallsky"
HOTSPOT_BAND="bg"
#HOTSPOT_BAND="a"

### Use this if you have multiple cameras
#HOTSPOT_SSID="IndiAllsky${RANDOM}"


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)


echo
echo "#######################################################"
echo "### Welcome to the indi-allsky hotspot setup script ###"
echo "#######################################################"

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run this script as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


if [[ -f "/etc/astroberry.version" ]]; then
    echo "Please do not run this script on an Astroberry server"
    echo "Astroberry has native hotspot support"
    echo
    echo
    exit 1
fi


echo
echo
echo "This script sets up a wifi hotspot for your Allsky camera"
echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo
echo
echo "SSID: $HOTSPOT_SSID"
echo "PSK:  $HOTSPOT_PSK"
echo "IP:   $HOTSPOT_IP"
echo "Band: $HOTSPOT_BAND"
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
        network-manager

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        network-manager

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        network-manager

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        network-manager

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        network-manager

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname $0)
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd $OLDPWD



echo "**** Setup policy kit permissions ****"
TMP8=$(mktemp)
sed \
 -e "s|%ALLSKY_USER%|$USER|g" \
 ${ALLSKY_DIRECTORY}/service/90-org.aaronwmorris.indi-allsky.pkla > $TMP8

sudo cp -f "$TMP8" "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chown root:root "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
sudo chmod 644 "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
[[ -f "$TMP8" ]] && rm -f "$TMP8"



if [[ -f "/etc/dhcpcd.conf" ]]; then
    if [[ ! $(grep -e "^denyinterfaces wlan0" /etc/dhcpcd.conf >/dev/null 2>&1) ]]; then
        echo "denyinterfaces wlan0" | sudo tee -a /etc/dhcpcd.conf
        sudo systemctl daemon-reload
        sudo systemctl restart dhcpcd
    fi
fi


sudo rfkill unblock wlan
nmcli radio wifi on

nmcli connection del HotSpot || true

sleep 5

nmcli connection add \
    ifname wlan0 \
    type wifi \
    con-name "HotSpot" \
    autoconnect no \
    wifi.mode ap \
    wifi.ssid "$HOTSPOT_SSID" \
    802-11-wireless.powersave 2 \
    802-11-wireless.band "$HOTSPOT_BAND" \
    ip4 "${HOTSPOT_IP}/24" \
    ipv6.method auto


nmcli connection modify HotSpot \
    wifi-sec.key-mgmt wpa-psk

nmcli connection modify HotSpot \
    wifi-sec.psk "$HOTSPOT_PSK"

# force WPA2 (rsn) and AES (ccmp)
nmcli connection modify HotSpot \
    802-11-wireless-security.proto rsn \
    802-11-wireless-security.group ccmp \
    802-11-wireless-security.pairwise ccmp

nmcli connection modify HotSpot \
    autoconnect yes


nmcli connection down HotSpot || true
sleep 3
nmcli connection up HotSpot


echo
echo
echo "Please reboot for the hotspot changes to take effect"
echo
echo
echo "SSID: $HOTSPOT_SSID"
echo "PSK:  $HOTSPOT_PSK"
echo
echo "Indi-Allsky HotSpot IP:  $HOTSPOT_IP  (255.255.255.0)"
echo "URL: https://${HOTSPOT_IP}/"
echo


