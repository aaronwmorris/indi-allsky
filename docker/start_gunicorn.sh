#!/bin/bash

#set -x  # command tracing
set -o errexit
set -o nounset

ALLSKY_DIRECTORY="${ALLSKY_DIRECTORY:-/usr/share/indi-allsky}"
ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
#DB_FILE="${DB_FOLDER}/indi-allsky.sqlite"
#SQLALCHEMY_DATABASE_URI="sqlite:///${DB_FILE}"
MIGRATION_FOLDER="${ALLSKY_DIRECTORY}/migrations"
DOCROOT_FOLDER="/var/www/html"
HTDOCS_FOLDER="${DOCROOT_FOLDER}/allsky"
INDISERVER_SERVICE_NAME="indiserver"
ALLSKY_SERVICE_NAME="indi-allsky"
GUNICORN_SERVICE_NAME="gunicorn-indi-allsky"


# ensure correct permissions
sudo chown -R indi-allsky:indi-allsky "$ALLSKY_ETC" "$DB_FOLDER" "$HTDOCS_FOLDER" 2>/dev/null || true


if [ "${INDIALLSKY_MARIADB_SSL:-false}" == "true" ]; then
    SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDIALLSKY_MARIADB_HOST}:${INDIALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity&charset=${INDIALLSKY_MARIADB_CHARSET}&collation=${INDIALLSKY_MARIADB_COLLATION}"
    #SQLALCHEMY_DATABASE_URI="mysql+pymysql://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDIALLSKY_MARIADB_HOST}:${INDIALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity=false&charset=${INDIALLSKY_MARIADB_CHARSET}"
else
    SQLALCHEMY_DATABASE_URI="mysql+mysqlconnector://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDIALLSKY_MARIADB_HOST}:${INDIALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}?charset=${INDIALLSKY_MARIADB_CHARSET}&collation=${INDIALLSKY_MARIADB_COLLATION}"
    #SQLALCHEMY_DATABASE_URI="mysql+pymysql://${MARIADB_USER}:${MARIADB_PASSWORD}@${INDIALLSKY_MARIADB_HOST}:${INDIALLSKY_MARIADB_PORT}/${MARIADB_DATABASE}?charset=${INDIALLSKY_MARIADB_CHARSET}"
fi


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
 --argjson oidc_enable "${INDIALLSKY_OIDC_ENABLE:-false}" \
 --arg oidc_client_id "${INDIALLSKY_OIDC_CLIENT_ID:-}" \
 --arg oidc_client_secret "${INDIALLSKY_OIDC_CLIENT_SECRET:-}" \
 --arg oidc_discovery "${INDIALLSKY_OIDC_DISCOVERY_ENDPOINT:-}" \
 '.SQLALCHEMY_DATABASE_URI = $sqlalchemy_database_uri | .INDI_ALLSKY_DOCROOT = $indi_allsky_docroot | .INDI_ALLSKY_AUTH_ALL_VIEWS = $indi_allsky_auth_all_views | .MIGRATION_FOLDER = $migration_folder | .ALLSKY_SERVICE_NAME = $allsky_service_name | .ALLSKY_TIMER_NAME = $allsky_timer_name | .INDISERVER_SERVICE_NAME = $indiserver_service_name | .INDISERVER_TIMER_NAME = $indiserver_timer_name | .GUNICORN_SERVICE_NAME = $gunicorn_service_name | .OIDC_ENABLE = $oidc_enable | .OIDC_CLIENT_ID = $oidc_client_id | .OIDC_CLIENT_SECRET = $oidc_client_secret | .OIDC_DISCOVERY_ENDPOINT = $oidc_discovery' \
 "${ALLSKY_DIRECTORY}/flask.json_template" > "$TMP_FLASK"
 

SECRET_KEY="${INDIALLSKY_FLASK_SECRET_KEY:-}"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "%INDIALLSKY_FLASK_SECRET_KEY%" ]; then
    SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
fi

PASSWORD_KEY="${INDIALLSKY_FLASK_PASSWORD_KEY:-}"
if [ -z "$PASSWORD_KEY" ] || [ "$PASSWORD_KEY" = "%INDIALLSKY_FLASK_PASSWORD_KEY%" ]; then
    PASSWORD_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
fi

TMP_FLASK_KEYS=$(mktemp --suffix=.json)
jq \
 --arg secret_key "$SECRET_KEY" \
 --arg password_key "$PASSWORD_KEY" \
 '.SECRET_KEY = $secret_key | .PASSWORD_KEY = $password_key' \
 "${TMP_FLASK}" > "$TMP_FLASK_KEYS"


cp -f "$TMP_FLASK_KEYS" "${ALLSKY_ETC}/flask.json"

[[ -f "$TMP_FLASK" ]] && rm -f "$TMP_FLASK"
[[ -f "$TMP_FLASK_KEYS" ]] && rm -f "$TMP_FLASK_KEYS"


json_pp < "$ALLSKY_ETC/flask.json" >/dev/null


cd "$ALLSKY_DIRECTORY"


# shellcheck disable=SC1091
if [ -f "/var/lib/indi-allsky/venv/bin/activate" ]; then
    source /var/lib/indi-allsky/venv/bin/activate
elif [ -f "/home/allsky/venv/bin/activate" ]; then
    source /home/allsky/venv/bin/activate
fi


if [ -z "${INDIALLSKY_GUNICORN_NO_WAIT:-}" ]; then
    # wait on database
    for X in $(seq 12); do
        echo "Waiting on database ($((65-(5*X)))s)"
        sleep 5
    done
else
    # shorter wait
    for X in $(seq 2); do
        echo "Waiting on database ($((15-(5*X)))s)"
        sleep 5
    done
fi


# Setup migration folder
if [[ ! -d "$MIGRATION_FOLDER" ]]; then
    # Folder defined in flask config
    flask db init
fi


flask db revision --autogenerate
flask db upgrade head


# bootstrap initial config
./config.py bootstrap || true

# dump config for processing
TMP_CONFIG_DUMP=$(mktemp --suffix=.json)
./config.py dump > "$TMP_CONFIG_DUMP"


# replace the flask IMAGE_FOLDER
TMP_FLASK_3=$(mktemp --suffix=.json)
jq --arg image_folder "$INDIALLSKY_IMAGE_FOLDER" '.INDI_ALLSKY_IMAGE_FOLDER = $image_folder' "${ALLSKY_ETC}/flask.json" > "$TMP_FLASK_3"
cp -f "$TMP_FLASK_3" "${ALLSKY_ETC}/flask.json"
[[ -f "$TMP_FLASK_3" ]] && rm -f "$TMP_FLASK_3"


# update image folder config
TMP_IMAGE_FOLDER=$(mktemp --suffix=.json)
jq \
 --arg image_folder "$INDIALLSKY_IMAGE_FOLDER" \
 '.IMAGE_FOLDER = $image_folder' \
 "$TMP_CONFIG_DUMP" > "$TMP_IMAGE_FOLDER"


# load all changes
./config.py load -c "$TMP_IMAGE_FOLDER" --force
[[ -f "$TMP_CONFIG_DUMP" ]] && rm -f "$TMP_CONFIG_DUMP"
[[ -f "$TMP_IMAGE_FOLDER" ]] && rm -f "$TMP_IMAGE_FOLDER"


USER_COUNT=$("${ALLSKY_DIRECTORY}/config.py" user_count)
# there is a system user
if [ "$USER_COUNT" -le 1 ]; then
    "$ALLSKY_DIRECTORY/misc/usertool.py" adduser -u "$INDIALLSKY_WEB_USER" -p "$INDIALLSKY_WEB_PASS" -f "$INDIALLSKY_WEB_NAME" -e "$INDIALLSKY_WEB_EMAIL"
    "$ALLSKY_DIRECTORY/misc/usertool.py" setadmin -u "$INDIALLSKY_WEB_USER"
fi


if [ "${INDIALLSKY_WEB_GENERATE_APIKEY:-false}" == "true" ]; then
    "$ALLSKY_DIRECTORY/misc/usertool.py" genapikey -u "$INDIALLSKY_WEB_USER"
    echo "!!!! REMEMBER TO SET INDIALLSKY_WEB_GENERATE_APIKEY BACK TO \"false\" !!!!"
    sleep 10
fi


echo -n "System timezone: "
cat /etc/timezone || true

# log the date (shows timezone)
date


# Log to stderr
export GUNICORN_ERROR_LOG_HANDLER=wsgi


# Environment variable to indicate running in containerized environment
export INDIALLSKY_DOCKER=1


# start the program
exec gunicorn \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --threads 8 \
    --timeout 180 \
    --umask 0022 \
    --log-level info \
    indi_allsky.wsgi

