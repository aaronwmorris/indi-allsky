#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

PATH=/usr/bin:/bin
export PATH


ALLSKY_DIRECTORY="/home/allsky/indi-allsky"
ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="$DB_FOLDER/migrations"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"
INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"


# shellcheck disable=SC1091
source /home/allsky/venv/bin/activate


TMP_FLASK=$(mktemp --suffix=.json)
jq \
 --arg sqlalchemy_database_uri "$SQLALCHEMY_DATABASE_URI" \
 --arg indi_allsky_docroot "$HTDOCS_FOLDER" \
 --argjson indi_allsky_auth_all_views "$INDIALLSKY_FLASK_AUTH_ALL_VIEWS" \
 --arg migration_folder "$MIGRATION_FOLDER" \
 --arg allsky_service_name "${ALLSKY_SERVICE_NAME}.service" \
 --arg allsky_timer_name "${ALLSKY_SERVICE_NAME}.timer" \
 --arg indiserver_service_name "${INDISERVER_SERVICE_NAME}.service" \
 --arg indiserver_timer_name "${INDISERVER_SERVICE_NAME}.timer" \
 --arg gunicorn_service_name "${GUNICORN_SERVICE_NAME}.service" \
 '.SQLALCHEMY_DATABASE_URI = $sqlalchemy_database_uri | .INDI_ALLSKY_DOCROOT = $indi_allsky_docroot | .INDI_ALLSKY_AUTH_ALL_VIEWS = $indi_allsky_auth_all_views | .MIGRATION_FOLDER = $migration_folder | .ALLSKY_SERVICE_NAME = $allsky_service_name | .ALLSKY_TIMER_NAME = $allsky_timer_name | .INDISERVER_SERVICE_NAME = $indiserver_service_name | .INDISERVER_TIMER_NAME = $indiserver_timer_name | .GUNICORN_SERVICE_NAME = $gunicorn_service_name' \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"

cp -f "$TMP_FLASK" "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"


json_pp < "$ALLSKY_ETC/flask.json" >/dev/null


# Setup migration folder
if [[ ! -d "$MIGRATION_FOLDER" ]]; then
    # Folder defined in flask config
    flask db init
fi


flask db revision --autogenerate
flask db upgrade head


cd "$ALLSKY_DIRECTORY"


# bootstrap initial config
"${ALLSKY_DIRECTORY}/config.py" bootstrap || true

# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
"${ALLSKY_DIRECTORY}/config.py" dump > "$TMP_CONFIG_DUMP"


# Detect IMAGE_FOLDER
IMAGE_FOLDER=$(jq -r '.IMAGE_FOLDER' "$TMP_CONFIG_DUMP")
echo "Detected IMAGE_FOLDER: $IMAGE_FOLDER"


# replace the flask IMAGE_FOLDER
TMP_FLASK_3=$(mktemp --suffix=.json)
jq --arg image_folder "$IMAGE_FOLDER" '.INDI_ALLSKY_IMAGE_FOLDER = $image_folder' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_3"
cp -f "$TMP_FLASK_3" "${ALLSKY_ETC}/flask.json"
[[ -f "$TMP_FLASK_3" ]] && rm -f "$TMP_FLASK_3"

# load all changes
"${ALLSKY_DIRECTORY}/config.py" load -c "$TMP_CONFIG_DUMP" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"



# start the program
gunicorn \
    --config service/gunicorn.conf.py \
    --bind 0.0.0.0:8000 \
    indi_allsky.wsgi


