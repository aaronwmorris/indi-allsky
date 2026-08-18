#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


# find script directory for service setup
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR"
DOCKER_DIRECTORY=$PWD
cd "$OLDPWD"



if [ ! -f "${DOCKER_DIRECTORY}/.env" ]; then
    sudo true

    sudo apt-get update
    sudo apt-get -y install \
        python3-cryptography \
        whiptail


    INDIALLSKY_FLASK_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex())')
    INDIALLSKY_FLASK_PASSWORD_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')


    MARIADB_PASSWORD=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 32)


    while [ -z "${WEB_USER:-}" ]; do
        # shellcheck disable=SC2068
        WEB_USER=$(whiptail --title "Username" --nocancel --inputbox "Please enter a username to login" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_PASS:-}" ]; do
        # shellcheck disable=SC2068
        WEB_PASS=$(whiptail --title "Password" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "${#WEB_PASS}" -lt 8 ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Password needs to be at least 8 characters" 0 0
            continue
        fi


        WEB_PASS2=$(whiptail --title "Password (#2)" --nocancel --passwordbox "Please enter the password (8+ chars)" 0 0 3>&1 1>&2 2>&3)

        if [ "$WEB_PASS" != "$WEB_PASS2" ]; then
            WEB_PASS=""
            whiptail --msgbox "Error: Passwords did not match" 0 0
            continue
        fi

    done

    while [ -z "${WEB_NAME:-}" ]; do
        # shellcheck disable=SC2068
        WEB_NAME=$(whiptail --title "Full Name" --nocancel --inputbox "Please enter the users name" 0 0 3>&1 1>&2 2>&3)
    done

    while [ -z "${WEB_EMAIL:-}" ]; do
        # shellcheck disable=SC2068
        WEB_EMAIL=$(whiptail --title "Email" --nocancel --inputbox "Please enter the users email\n\nThe email address is only stored on your local system and is not transmitted" 0 0 3>&1 1>&2 2>&3)
    done


    sed \
     -e "s|%INDIALLSKY_FLASK_SECRET_KEY%|$INDIALLSKY_FLASK_SECRET_KEY|g" \
     -e "s|%INDIALLSKY_FLASK_PASSWORD_KEY%|$INDIALLSKY_FLASK_PASSWORD_KEY|g" \
     -e "s|%WEB_USER%|$WEB_USER|g" \
     -e "s|%WEB_PASS%|$WEB_PASS|g" \
     -e "s|%WEB_NAME%|$WEB_NAME|g" \
     -e "s|%WEB_EMAIL%|$WEB_EMAIL|g" \
     -e "s|%MARIADB_PASSWORD%|$MARIADB_PASSWORD|g" \
     "${DOCKER_DIRECTORY}/env_template" > "${DOCKER_DIRECTORY}/.env"

else
    echo
    echo ".env is already defined"
fi


if [[ ! -f "${DOCKER_DIRECTORY}/ssl.crt" || ! -f "${DOCKER_DIRECTORY}/ssl.key" ]]; then
    rm -f "${DOCKER_DIRECTORY}/ssl.crt"
    rm -f "${DOCKER_DIRECTORY}/ssl.key"

    SHORT_HOSTNAME=$(hostname -s)

    openssl req \
        -new \
        -newkey rsa:4096 \
        -sha512 \
        -days 3650 \
        -nodes \
        -x509 \
        -subj "/CN=${SHORT_HOSTNAME}.local" \
        -keyout "${DOCKER_DIRECTORY}/ssl.key" \
        -out "${DOCKER_DIRECTORY}/ssl.crt" \
        -extensions san \
        -config <(cat /etc/ssl/openssl.cnf <(printf "\n[req]\ndistinguished_name=req\n[san]\nsubjectAltName=DNS:%s.local,DNS:%s,DNS:localhost" "$SHORT_HOSTNAME" "$SHORT_HOSTNAME"))

else
    echo
    echo "certificates are already generated"
fi


# always do this
chmod 600 "${DOCKER_DIRECTORY}/.env"
chmod 600 "${DOCKER_DIRECTORY}/ssl.key"
