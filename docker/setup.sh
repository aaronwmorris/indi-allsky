#!/bin/bash

set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


PYTHON_BIN=python3

ALLSKY_DIRECTORY=/home/allsky/indi-allsky

INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"

ALLSKY_ETC=/etc/indi-allsky
DB_FOLDER="/var/lib/indi-allsky"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"

FLASK_AUTH_ALL_VIEWS="${INDIALLSKY_FLASK_AUTH_ALL_VIEWS:-false}"
HTTP_PORT="${INDIALLSKY_HTTP_PORT:-80}"
HTTPS_PORT="${INDIALLSKY_HTTPS_PORT:-443}"


echo "**** Indi-allsky config ****"
[[ ! -d "$ALLSKY_ETC" ]] && sudo mkdir "$ALLSKY_ETC"
sudo chown -R "$USER":"$PGRP" "$ALLSKY_ETC"
sudo chmod 775 "${ALLSKY_ETC}"

if [[ ! -f "${ALLSKY_ETC}/config.json" ]]; then
    # create new config
    cp "${ALLSKY_DIRECTORY}/config.json_template" "${ALLSKY_ETC}/config.json"
fi

sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/config.json"
sudo chmod 660 "${ALLSKY_ETC}/config.json"


SQLALCHEMY_DATABASE_URI=$(jq -r '.SQLALCHEMY_DATABASE_URI' "${ALLSKY_ETC}/config.json")
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "${ALLSKY_ETC}/config.json")


TMP_FLASK=$(mktemp)
TMP_FLASK_2=$(mktemp)
TMP_FLASK_MERGE=$(mktemp)

SECRET_KEY=$(${PYTHON_BIN} -c 'import secrets; print(secrets.token_hex())')
sed \
 -e "s|%SQLALCHEMY_DATABASE_URI%|$SQLALCHEMY_DATABASE_URI|g" \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%SECRET_KEY%|$SECRET_KEY|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%HTDOCS_FOLDER%|$HTDOCS_FOLDER|g" \
 -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
 -e "s|%INDISERVER_SERVICE_NAME%|$INDISERVER_SERVICE_NAME|g" \
 -e "s|%ALLSKY_SERVICE_NAME%|$ALLSKY_SERVICE_NAME|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%FLASK_AUTH_ALL_VIEWS%|$FLASK_AUTH_ALL_VIEWS|g" \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"

# syntax check
json_pp < "$TMP_FLASK" >/dev/null


if [[ -f "${ALLSKY_ETC}/flask.json" ]]; then
    # attempt to merge configs giving preference to the original config (listed 2nd)
    jq -s '.[0] * .[1]' "$TMP_FLASK" "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_MERGE"
    cp -f "$TMP_FLASK_MERGE" "${ALLSKY_ETC}/flask.json"
else
    # new config
    cp -f "$TMP_FLASK" "${ALLSKY_ETC}/flask.json"
fi


# always replace the DB URI
jq --arg sqlalchemy_database_uri "$SQLALCHEMY_DATABASE_URI" '.SQLALCHEMY_DATABASE_URI = $sqlalchemy_database_uri' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_2"
cp -f "$TMP_FLASK_2" "${ALLSKY_ETC}/flask.json"


sudo chown "$USER":"$PGRP" "${ALLSKY_ETC}/flask.json"
sudo chmod 660 "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_2" ]] && rm -f "$TMP_FLASK_2"
[[ -f "$TMP_FLASK_MERGE" ]] && rm -f "$TMP_FLASK_MERGE"



TMP7=$(mktemp)
cat "${ALLSKY_DIRECTORY}/service/gunicorn.conf.py" > "$TMP7"

cp -f "$TMP7" "${ALLSKY_ETC}/gunicorn.conf.py"
chmod 644 "${ALLSKY_ETC}/gunicorn.conf.py"
[[ -f "$TMP7" ]] && rm -f "$TMP7"


echo "**** Setup nginx ****"
TMP3=$(mktemp)
sed \
 -e "s|%ALLSKY_DIRECTORY%|$ALLSKY_DIRECTORY|g" \
 -e "s|%GUNICORN_SERVICE_NAME%|$GUNICORN_SERVICE_NAME|g" \
 -e "s|%DB_FOLDER%|$DB_FOLDER|g" \
 -e "s|%ALLSKY_ETC%|$ALLSKY_ETC|g" \
 -e "s|%DOCROOT_FOLDER%|$DOCROOT_FOLDER|g" \
 -e "s|%IMAGE_FOLDER%|$IMAGE_FOLDER|g" \
 -e "s|%HTTP_PORT%|$HTTP_PORT|g" \
 -e "s|%HTTPS_PORT%|$HTTPS_PORT|g" \
 "${ALLSKY_DIRECTORY}/service/nginx_astroberry_ssl" > "$TMP3"

sudo cp -f "$TMP3" "$ALLSKY_ETC/nginx.conf"
sudo chown root:root "$ALLSKY_ETC/nginx.conf"
sudo chmod 644 "$ALLSKY_ETC/nginx.conf"


if [[ ! -f "$ALLSKY_ETC/self-signed.key" || ! -f "$ALLSKY_ETC/self-signed.pem" ]]; then
    sudo rm -f "$ALLSKY_ETC/self-signed.key"
    sudo rm -f "$ALLSKY_ETC/self-signed.pem"

    SHORT_HOSTNAME=indi-allsky
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

        sudo cp -f "$KEY_TMP" "$ALLSKY_ETC/self-signed.key"
        sudo cp -f "$CRT_TMP" "$ALLSKY_ETC/self-signed.pem"

        rm -f "$KEY_TMP"
        rm -f "$CRT_TMP"
fi


sudo chown root:root "$ALLSKY_ETC/self-signed.key"
sudo chmod 600 "$ALLSKY_ETC/self-signed.key"
sudo chown root:root "$ALLSKY_ETC/self-signed.pem"
sudo chmod 644 "$ALLSKY_ETC/self-signed.pem"


# system certificate store
sudo cp -f "$ALLSKY_ETC/self-signed.pem" /usr/local/share/ca-certificates/indi-allsky.crt
sudo chown root:root /usr/local/share/ca-certificates/indi-allsky.crt
sudo chmod 644 /usr/local/share/ca-certificates/indi-allsky.crt
sudo update-ca-certificates



