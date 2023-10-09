#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset


PATH=/bin:/usr/bin
export PATH


DISTRO_NAME=$(lsb_release -s -i)
DISTRO_RELEASE=$(lsb_release -s -r)
CPU_ARCH=$(uname -m)

M_USERNAME="indi-allsky"

echo
echo "#########################################################"
echo "### Welcome to the indi-allsky mosquitto setup script ###"
echo "#########################################################"

if [[ "$(id -u)" == "0" ]]; then
    echo "Please do not run this script as root"
    echo "Re-run this script as the user which will execute the indi-allsky software"
    echo
    echo
    exit 1
fi


echo
echo
echo "This script sets up mosquitto MQTT server"
echo
echo
echo "Distribution: $DISTRO_NAME"
echo "Release: $DISTRO_RELEASE"
echo "Arch: $CPU_ARCH"
echo
echo
echo


echo "Setup proceeding in 10 seconds... (control-c to cancel)"
echo
sleep 10


# Run sudo to ask for initial password
sudo true


echo "**** Installing packages... ****"
if [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "12" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "11" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Raspbian" && "$DISTRO_RELEASE" == "10" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "12" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "11" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Debian" && "$DISTRO_RELEASE" == "10" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "22.04" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

elif [[ "$DISTRO_NAME" == "Ubuntu" && "$DISTRO_RELEASE" == "20.04" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        ca-certificates

else
    echo "Unknown distribution $DISTRO_NAME $DISTRO_RELEASE ($CPU_ARCH)"
    exit 1
fi


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR/.."
ALLSKY_DIRECTORY=$PWD
cd "$OLDPWD"


echo "**** Setup certificate ****"

if [[ ! -d "/etc/mosquitto/certs" ]]; then
    sudo mkdir /etc/mosquitto/certs
fi

sudo chown root:root /etc/mosquitto/certs
sudo chmod 755 /etc/mosquitto/certs


if [[ ! -f "/etc/mosquitto/certs/indi-allsky_mosquitto.key" || ! -f "/etc/mosquitto/certs/indi-allsky_mosquitto.crt" ]]; then
    sudo rm -f /etc/mosquitto/certs/indi-allsky_mosquitto.key
    sudo rm -f /etc/mosquitto/certs/indi-allsky_mosquitto.crt

    SHORT_HOSTNAME=$(hostname -s)
    KEY_TMP=$(mktemp)
    CRT_TMP=$(mktemp)

    # sudo has problems with process substitution <()
    openssl req \
        -new \
        -newkey rsa:4096 \
        -sha512 \
        -days 3650 \
        -nodes \
        -x509 \
        -subj "/CN=${SHORT_HOSTNAME}.local" \
        -keyout "$KEY_TMP" \
        -out "$CRT_TMP" \
        -extensions san \
        -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))


    sudo cp -f "$KEY_TMP" /etc/mosquitto/certs/indi-allsky_mosquitto.key
    sudo cp -f "$CRT_TMP" /etc/mosquitto/certs/indi-allsky_mosquitto.crt

    rm -f "$KEY_TMP"
    rm -f "$CRT_TMP"
fi


sudo chown root:${MOSQUITTO_GROUP} /etc/mosquitto/certs/indi-allsky_mosquitto.key
sudo chmod 640 /etc/mosquitto/certs/indi-allsky_mosquitto.key
sudo chown root:${MOSQUITTO_GROUP} /etc/mosquitto/certs/indi-allsky_mosquitto.crt
sudo chmod 644 /etc/mosquitto/certs/indi-allsky_mosquitto.crt

# system certificate store
sudo cp -f /etc/mosquitto/certs/indi-allsky_mosquitto.crt /usr/local/share/ca-certificates/indi-allsky_mosquitto.crt
sudo chown root:root /usr/local/share/ca-certificates/indi-allsky_mosquitto.crt
sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky_mosquitto.crt
sudo update-ca-certificates


echo "**** Setup mosquitto config ****"
TMP1=$(mktemp)
cat "${ALLSKY_DIRECTORY}/misc/mosquitto_indi-allsky.conf" > "$TMP1"

sudo cp -f "$TMP1" "/etc/mosquitto/conf.d/mosquitto_indi-allsky.conf"
sudo chown root:root "/etc/mosquitto/conf.d/mosquitto_indi-allsky.conf"
sudo chmod 644 "/etc/mosquitto/conf.d/mosquitto_indi-allsky.conf"
[[ -f "$TMP1" ]] && rm -f "$TMP1"


echo
echo "Please enter a password for the $M_USERNAME mqtt user"
echo

if [[ -f "/etc/mosquitto/passwd" ]]; then
    sudo mosquitto_passwd /etc/mosquitto/passwd "$M_USERNAME"
else
    sudo mosquitto_passwd -c /etc/mosquitto/passwd "$M_USERNAME"
fi


sudo chown root:${MOSQUITTO_GROUP} /etc/mosquitto/passwd
sudo chmod 640 /etc/mosquitto/passwd


echo
echo "Use this password in the indi-allsky configuration"
echo


sudo systemctl enable mosquitto
sudo systemctl restart mosquitto




echo
echo
echo "mosquitto is now installed... enjoy"
echo
echo

