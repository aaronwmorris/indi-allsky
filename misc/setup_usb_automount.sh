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


echo
echo "#######################################################"
echo "### Welcome to the indi-allsky USB automount script ###"
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
    echo "Astroberry has native automount support"
    echo
    echo
    exit 1
fi


echo
echo
echo "This script sets up USB automount (udisks2) for your Allsky camera"
echo
echo
echo "Distribution: $DISTRO_ID"
echo "Release: $DISTRO_VERSION_ID"
echo "Arch: $CPU_ARCH"
echo
echo
echo


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
        udisks2 \
        udiskie \
        exfatprogs \
        dosfstools

elif [[ "$DISTRO" == "debian_12" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfatprogs \
        dosfstools

elif [[ "$DISTRO" == "debian_11" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfatprogs \
        dosfstools

elif [[ "$DISTRO" == "debian_10" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfat-utils \
        dosfstools

elif [[ "$DISTRO" == "ubuntu_24.04" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfatprogs \
        dosfstools

elif [[ "$DISTRO" == "ubuntu_22.04" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfatprogs \
        dosfstools

elif [[ "$DISTRO" == "ubuntu_20.04" ]]; then

    sudo apt-get update
    sudo apt-get -y install \
        udisks2 \
        udiskie \
        exfat-utils \
        dosfstools

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"



echo "**** Setup policy kit permissions ****"
TMP_POLKIT=$(mktemp)

if [ -d "/etc/polkit-1/rules.d" ]; then
    sed \
     -e "s|%ALLSKY_USER%|$USER|g" \
     "${ALLSKY_DIRECTORY}/service/90-indi-allsky.rules" > "$TMP_POLKIT"

    sudo cp -f "$TMP_POLKIT" "/etc/polkit-1/rules.d/90-indi-allsky.rules"
    sudo chown root:root "/etc/polkit-1/rules.d/90-indi-allsky.rules"
    sudo chmod 644 "/etc/polkit-1/rules.d/90-indi-allsky.rules"

    # remove legacy config
    if sudo test -f "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"; then
        sudo rm -f "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    fi
else
    # legacy pkla
    sed \
     -e "s|%ALLSKY_USER%|$USER|g" \
     "${ALLSKY_DIRECTORY}/service/90-org.aaronwmorris.indi-allsky.pkla" > "$TMP_POLKIT"

    sudo cp -f "$TMP_POLKIT" "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    sudo chown root:root "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
    sudo chmod 644 "/etc/polkit-1/localauthority/50-local.d/90-org.aaronwmorris.indi-allsky.pkla"
fi

[[ -f "$TMP_POLKIT" ]] && rm -f "$TMP_POLKIT"

sudo systemctl restart polkit


# create users systemd folder
[[ ! -d "${HOME}/.config/systemd/user" ]] && mkdir -p "${HOME}/.config/systemd/user"


cp -f "${ALLSKY_DIRECTORY}/service/udiskie-automount.service" "${HOME}/.config/systemd/user/udiskie-automount.service"
chmod 644 "${HOME}/.config/systemd/user/udiskie-automount.service"


systemctl --user daemon-reload
systemctl --user enable udiskie-automount.service
systemctl --user start udiskie-automount.service


echo
echo "Please insert your USB media now"
echo
# shellcheck disable=SC2034
read -n1 -r -p "Press any key to continue..." anykey


# Allow web server access to mounted media
if [[ -d "/media/${USER}" ]]; then
    sudo chmod ugo+x "/media/${USER}"
else
    echo
    echo
    echo "Media not detected..."
    echo "You may need to run this script again once you insert your media"
    echo "for the correct access permissions for the web server"
    echo
fi


echo
echo
echo "USB automounting is now enabled... enjoy"
echo
echo


