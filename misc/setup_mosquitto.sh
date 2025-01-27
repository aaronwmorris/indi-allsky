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


echo "**** Installing packages... ****"
if [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "12" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "11" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "raspbian" && "$DISTRO_VERSION_ID" == "10" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "12" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "11" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "debian" && "$DISTRO_VERSION_ID" == "10" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "24.04" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "22.04" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

elif [[ "$DISTRO_ID" == "ubuntu" && "$DISTRO_VERSION_ID" == "20.04" ]]; then
    #MOSQUITTO_USER=mosquitto
    MOSQUITTO_GROUP=mosquitto

    sudo apt-get update
    sudo apt-get -y install \
        mosquitto \
        mosquitto-clients \
        mosquitto-dev \
        whiptail \
        ca-certificates

else
    echo "Unknown distribution $DISTRO_ID $DISTRO_VERSION_ID ($CPU_ARCH)"
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
    KEY_TMP=$(mktemp --suffix=.key)
    CRT_TMP=$(mktemp --suffix=.crt)

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



while [ -z "${M_USER:-}" ]; do
    # shellcheck disable=SC2068
    M_USER=$(whiptail --title "Username" --nocancel --inputbox "Please enter a username for mosquitto" 0 0 3>&1 1>&2 2>&3)
done

while [ -z "${M_PASS:-}" ]; do
    # shellcheck disable=SC2068
    M_PASS=$(whiptail --title "Password" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

    if [ "${#M_PASS}" -lt 8 ]; then
        M_PASS=""
        whiptail --msgbox "Error: Password needs to be at least 8 characters" 0 0
        continue
    fi


    M_PASS2=$(whiptail --title "Password (#2)" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

    if [ "$M_PASS" != "$M_PASS2" ]; then
        M_PASS=""
        whiptail --msgbox "Error: Passwords did not match" 0 0
        continue
    fi
done


if [[ -f "/etc/mosquitto/passwd" ]]; then
    sudo mosquitto_passwd -b /etc/mosquitto/passwd "$M_USER" "$M_PASS"
else
    sudo mosquitto_passwd -b -c /etc/mosquitto/passwd "$M_USER" "$M_PASS"
fi


sudo chown root:${MOSQUITTO_GROUP} /etc/mosquitto/passwd
sudo chmod 640 /etc/mosquitto/passwd


sudo systemctl enable mosquitto
sudo systemctl restart mosquitto


echo
echo "##################################################"
echo "Username for mosquitto configuration: $M_USER"
echo "##################################################"
echo


echo
echo
echo "mosquitto is now installed... enjoy"
echo
echo

