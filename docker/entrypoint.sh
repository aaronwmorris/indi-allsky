#!/bin/bash
set -o errexit
set -o nounset

PATH=/var/lib/indi-allsky/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
export GUNICORN_ERROR_LOG_HANDLER=wsgi
export FLASK_APP=app.py

ALLSKY_DIRECTORY="/usr/share/indi-allsky"
ALLSKY_ETC="/etc/indi-allsky"
DB_FOLDER="/var/lib/indi-allsky"
MIGRATION_FOLDER="${DB_FOLDER}/migrations"
DOCROOT_FOLDER="/var/www/html/allsky"
IMAGE_FOLDER="${INDIALLSKY_IMAGE_FOLDER:-$DOCROOT_FOLDER/images}"

# Ensure required runtime directories exist
mkdir -p "$ALLSKY_ETC" "$DB_FOLDER" "$MIGRATION_FOLDER" "$DOCROOT_FOLDER" "$IMAGE_FOLDER"

# Setup hardware and system groups and folder ownership for indi-allsky
if id "indi-allsky" >/dev/null 2>&1; then
    usermod -a -G dialout,video,plugdev,www-data indi-allsky 2>/dev/null || true
    for grp in gpio i2c spi adm; do
        if getent group "$grp" >/dev/null 2>&1; then
            usermod -a -G "$grp" indi-allsky 2>/dev/null || true
        fi
    done
    chown -R indi-allsky:indi-allsky "$ALLSKY_ETC" "$DB_FOLDER" 2>/dev/null || true
    if [ "$(stat -c '%U' "$DOCROOT_FOLDER" 2>/dev/null)" != "indi-allsky" ]; then
        chown -R indi-allsky:www-data "$DOCROOT_FOLDER" 2>/dev/null || true
    fi
    chmod 775 "$DOCROOT_FOLDER" "$IMAGE_FOLDER" 2>/dev/null || true
fi

# Update timezone if specified
if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

run_as_app_user() {
    local gosu_bin="gosu"
    if [ -x "/usr/sbin/gosu" ]; then
        gosu_bin="/usr/sbin/gosu"
    fi

    if [ "$(id -u)" = "0" ] && id "indi-allsky" >/dev/null 2>&1; then
        exec "$gosu_bin" indi-allsky "$@"
    else
        exec "$@"
    fi
}

generate_flask_json() {
    local sql_uri
    if [ "${INDIALLSKY_MARIADB_SSL:-false}" = "true" ]; then
        sql_uri="mysql+mysqlconnector://${MARIADB_USER:-indi_allsky_own}:${MARIADB_PASSWORD:-}@${INDIALLSKY_MARIADB_HOST:-mariadb.indi.allsky}:${INDIALLSKY_MARIADB_PORT:-3306}/${MARIADB_DATABASE:-indi_allsky}?ssl_ca=/etc/ssl/certs/ca-certificates.crt&ssl_verify_identity&charset=${INDIALLSKY_MARIADB_CHARSET:-utf8mb4}&collation=${INDIALLSKY_MARIADB_COLLATION:-utf8mb4_unicode_ci}"
    else
        sql_uri="mysql+mysqlconnector://${MARIADB_USER:-indi_allsky_own}:${MARIADB_PASSWORD:-}@${INDIALLSKY_MARIADB_HOST:-mariadb.indi.allsky}:${INDIALLSKY_MARIADB_PORT:-3306}/${MARIADB_DATABASE:-indi_allsky}?charset=${INDIALLSKY_MARIADB_CHARSET:-utf8mb4}&collation=${INDIALLSKY_MARIADB_COLLATION:-utf8mb4_unicode_ci}"
    fi

    SQL_URI="$sql_uri" \
    DOCROOT_FOLDER="$DOCROOT_FOLDER" \
    IMAGE_FOLDER="$IMAGE_FOLDER" \
    MIGRATION_FOLDER="$MIGRATION_FOLDER" \
    ALLSKY_DIRECTORY="$ALLSKY_DIRECTORY" \
    ALLSKY_ETC="$ALLSKY_ETC" \
    python3 -c "
import json, os, secrets, base64

template_path = os.environ['ALLSKY_DIRECTORY'] + '/flask.json_template'
dest_path = os.environ['ALLSKY_ETC'] + '/flask.json'

with open(template_path, 'r') as f:
    cfg = json.load(f)

# If existing flask.json exists, preserve custom / existing values
if os.path.isfile(dest_path):
    try:
        with open(dest_path, 'r') as f:
            existing = json.load(f)
            cfg.update(existing)
    except Exception:
        pass

# Database URI & runtime paths
cfg['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQL_URI', cfg.get('SQLALCHEMY_DATABASE_URI'))
cfg['INDI_ALLSKY_DOCROOT'] = os.environ.get('DOCROOT_FOLDER', '/var/www/html/allsky')
cfg['INDI_ALLSKY_IMAGE_FOLDER'] = os.environ.get('IMAGE_FOLDER', '/var/www/html/allsky/images')
cfg['MIGRATION_FOLDER'] = os.environ.get('MIGRATION_FOLDER', '/var/lib/indi-allsky/migrations')

# Encryption keys
if os.environ.get('INDIALLSKY_FLASK_SECRET_KEY'):
    cfg['SECRET_KEY'] = os.environ['INDIALLSKY_FLASK_SECRET_KEY']
elif not cfg.get('SECRET_KEY') or cfg.get('SECRET_KEY') == 'CHANGEME':
    cfg['SECRET_KEY'] = secrets.token_hex(24)

if os.environ.get('INDIALLSKY_FLASK_PASSWORD_KEY'):
    cfg['PASSWORD_KEY'] = os.environ['INDIALLSKY_FLASK_PASSWORD_KEY']
elif not cfg.get('PASSWORD_KEY') or cfg.get('PASSWORD_KEY') == 'CHANGEME':
    cfg['PASSWORD_KEY'] = base64.urlsafe_b64encode(os.urandom(32)).decode()

def to_bool(val, default=False):
    if val is None or val == '': return default
    return str(val).strip().lower() in ('true', '1', 'yes')

def to_list(val):
    if not val: return []
    val = val.strip()
    if val.startswith('[') and val.endswith(']'):
        try: return json.loads(val)
        except Exception: pass
    return [x.strip() for x in val.split(',') if x.strip()]

# Web interface security and authentication flags
if 'INDIALLSKY_FLASK_AUTH_ALL_VIEWS' in os.environ:
    cfg['INDI_ALLSKY_AUTH_ALL_VIEWS'] = to_bool(os.environ['INDIALLSKY_FLASK_AUTH_ALL_VIEWS'], False)
if 'INDIALLSKY_FLASK_AUTH_MEDIA_VIEWS' in os.environ:
    cfg['INDI_ALLSKY_AUTH_MEDIA_VIEWS'] = to_bool(os.environ['INDIALLSKY_FLASK_AUTH_MEDIA_VIEWS'], False)
if 'INDIALLSKY_FLASK_LOCAL_AUTH_ENABLE' in os.environ:
    cfg['LOCAL_AUTH_ENABLE'] = to_bool(os.environ['INDIALLSKY_FLASK_LOCAL_AUTH_ENABLE'], True)
if 'INDIALLSKY_FLASK_LOGIN_DISABLED' in os.environ:
    cfg['LOGIN_DISABLED'] = to_bool(os.environ['INDIALLSKY_FLASK_LOGIN_DISABLED'], False)
if 'INDIALLSKY_FLASK_SESSION_COOKIE_SECURE' in os.environ:
    cfg['SESSION_COOKIE_SECURE'] = to_bool(os.environ['INDIALLSKY_FLASK_SESSION_COOKIE_SECURE'], True)

# OpenID Connect (OIDC / OAuth2 / SSO) settings
if 'INDIALLSKY_OIDC_ENABLE' in os.environ:
    cfg['OIDC_ENABLE'] = to_bool(os.environ['INDIALLSKY_OIDC_ENABLE'], False)
if 'INDIALLSKY_OIDC_AUTO_LOGIN' in os.environ:
    cfg['OIDC_AUTO_LOGIN'] = to_bool(os.environ['INDIALLSKY_OIDC_AUTO_LOGIN'], False)
if 'INDIALLSKY_OIDC_PROVIDER_NAME' in os.environ:
    cfg['OIDC_PROVIDER_NAME'] = os.environ['INDIALLSKY_OIDC_PROVIDER_NAME']
if 'INDIALLSKY_OIDC_CLIENT_ID' in os.environ:
    cfg['OIDC_CLIENT_ID'] = os.environ['INDIALLSKY_OIDC_CLIENT_ID']
if 'INDIALLSKY_OIDC_CLIENT_SECRET' in os.environ:
    cfg['OIDC_CLIENT_SECRET'] = os.environ['INDIALLSKY_OIDC_CLIENT_SECRET']
if 'INDIALLSKY_OIDC_DISCOVERY_ENDPOINT' in os.environ:
    cfg['OIDC_DISCOVERY_ENDPOINT'] = os.environ['INDIALLSKY_OIDC_DISCOVERY_ENDPOINT']
if 'INDIALLSKY_OIDC_USERINFO_ENDPOINT' in os.environ:
    cfg['OIDC_USERINFO_ENDPOINT'] = os.environ['INDIALLSKY_OIDC_USERINFO_ENDPOINT']
if 'INDIALLSKY_OIDC_USERNAME_CLAIM' in os.environ:
    cfg['OIDC_USERNAME_CLAIM'] = os.environ['INDIALLSKY_OIDC_USERNAME_CLAIM']
if 'INDIALLSKY_OIDC_SCOPES' in os.environ:
    cfg['OIDC_SCOPES'] = os.environ['INDIALLSKY_OIDC_SCOPES']
if 'INDIALLSKY_OIDC_PKCE' in os.environ:
    cfg['OIDC_PKCE'] = to_bool(os.environ['INDIALLSKY_OIDC_PKCE'], True)
if 'INDIALLSKY_OIDC_LOGO_URL' in os.environ:
    cfg['OIDC_LOGO_URL'] = os.environ['INDIALLSKY_OIDC_LOGO_URL']
if 'INDIALLSKY_OIDC_ALLOWED_GROUPS' in os.environ:
    cfg['OIDC_ALLOWED_GROUPS'] = to_list(os.environ['INDIALLSKY_OIDC_ALLOWED_GROUPS'])
if 'INDIALLSKY_OIDC_ADMIN_GROUPS' in os.environ:
    cfg['OIDC_ADMIN_GROUPS'] = to_list(os.environ['INDIALLSKY_OIDC_ADMIN_GROUPS'])
if 'INDIALLSKY_OIDC_ALLOWED_USERS' in os.environ:
    cfg['OIDC_ALLOWED_USERS'] = to_list(os.environ['INDIALLSKY_OIDC_ALLOWED_USERS'])
if 'INDIALLSKY_OIDC_ADMIN_USERS' in os.environ:
    cfg['OIDC_ADMIN_USERS'] = to_list(os.environ['INDIALLSKY_OIDC_ADMIN_USERS'])

tmp_out = dest_path + '.tmp'
with open(tmp_out, 'w') as f:
    json.dump(cfg, f, indent=4)
os.replace(tmp_out, dest_path)
"

    chown indi-allsky:indi-allsky "${ALLSKY_ETC}/flask.json" 2>/dev/null || true
    chmod 664 "${ALLSKY_ETC}/flask.json"
}

bootstrap_ssl_certificates() {
    local cert_dir="${ALLSKY_ETC}/certs"
    mkdir -p "$cert_dir"
    if [ ! -f "${cert_dir}/ssl.crt" ] || [ ! -f "${cert_dir}/ssl.key" ]; then
        echo "Generating self-signed SSL certificate in ${cert_dir}..."
        local hostname_short
        hostname_short=$(hostname -s 2>/dev/null || echo "indi-allsky")
        if ! openssl req -new -newkey rsa:2048 -days 3650 -nodes -x509 \
            -subj "/CN=${hostname_short}.local" \
            -addext "subjectAltName=DNS:${hostname_short}.local,DNS:${hostname_short},DNS:localhost,IP:127.0.0.1" \
            -keyout "${cert_dir}/ssl.key" \
            -out "${cert_dir}/ssl.crt"; then
            echo "ERROR: Failed to generate self-signed SSL certificates using openssl." >&2
        fi
    fi
    chmod 755 "$cert_dir" 2>/dev/null || true
    chmod 644 "${cert_dir}/ssl.key" "${cert_dir}/ssl.crt" 2>/dev/null || true
}

bootstrap_nginx_conf() {
    local nginx_out="${ALLSKY_ETC}/nginx.conf"
    local nginx_template="${ALLSKY_DIRECTORY}/service/nginx_indi-allsky.conf"
    if [ ! -f "$nginx_out" ] && [ -f "$nginx_template" ]; then
        echo "Rendering Nginx configuration to ${nginx_out}..."
        python3 -c "
import re

with open('${nginx_template}', 'r') as f:
    conf = f.read()

# Fix port-stripping HTTPS redirect so non-standard exposed ports work properly (run before replacing %HTTPS_PORT%)
conf = re.sub(r'rewrite\s+\^/\$\s+https://\$host(?::(?:443|%HTTPS_PORT%))?/indi-allsky;?', 'rewrite ^/$ /indi-allsky permanent;', conf)

conf = conf.replace('%UPSTREAM_SERVER%', 'gunicorn.indi.allsky:8000')
conf = conf.replace('%HTTP_PORT%', '80')
conf = conf.replace('%HTTPS_PORT%', '443')
conf = conf.replace('%DOCROOT_FOLDER%', '${DOCROOT_FOLDER}')
conf = conf.replace('%IMAGE_FOLDER%', '${IMAGE_FOLDER}')
conf = conf.replace('%ALLSKY_DIRECTORY%', '${ALLSKY_DIRECTORY}')
conf = conf.replace('/etc/nginx/ssl/indi-allsky_nginx.pem', '/etc/indi-allsky/certs/ssl.crt')
conf = conf.replace('/etc/nginx/ssl/indi-allsky_nginx.key', '/etc/indi-allsky/certs/ssl.key')

# Strip all 'location /indi-allsky/static { ... }' blocks
def strip_nested_block(text, marker):
    result = []
    i = 0
    while i < len(text):
        match = re.search(marker, text[i:])
        if not match:
            result.append(text[i:])
            break
        result.append(text[i:i + match.start()])
        brace_start = i + match.start() + text[i + match.start():].index('{')
        depth, j = 1, brace_start + 1
        while j < len(text) and depth > 0:
            if text[j] == '{': depth += 1
            elif text[j] == '}': depth -= 1
            j += 1
        if j < len(text) and text[j] == '\n': j += 1
        i = j
    return ''.join(result)

conf = strip_nested_block(conf, r'location\s+/indi-allsky/static\s*\{')

with open('${nginx_out}', 'w') as f:
    f.write(conf)
" 2>/dev/null || true
        chmod 644 "$nginx_out" 2>/dev/null || true
    fi
}

bootstrap_mosquitto_conf() {
    local mosq_out="${ALLSKY_ETC}/mosquitto.conf"
    local mosq_template="${ALLSKY_DIRECTORY}/service/mosquitto_indi-allsky.conf"
    if [ ! -f "$mosq_out" ] && [ -f "$mosq_template" ]; then
        echo "Rendering Mosquitto configuration to ${mosq_out}..."
        python3 -c "
with open('${mosq_template}', 'r') as f:
    conf = f.read()

conf = conf.replace('/etc/mosquitto/passwd', '/mosquitto/data/passwd')
conf = conf.replace('/etc/mosquitto/certs/indi-allsky_mosquitto.crt', '/etc/indi-allsky/certs/ssl.crt')
conf = conf.replace('/etc/mosquitto/certs/indi-allsky_mosquitto.key', '/etc/indi-allsky/certs/ssl.key')

# Enable persistent storage in Mosquitto data volume
conf += '\n\npersistence true\npersistence_location /mosquitto/data/\n'

with open('${mosq_out}', 'w') as f:
    f.write(conf)
" 2>/dev/null || true
        chmod 644 "$mosq_out" 2>/dev/null || true
    fi
}

wait_for_database() {
    local host="${INDIALLSKY_MARIADB_HOST:-mariadb.indi.allsky}"
    local port="${INDIALLSKY_MARIADB_PORT:-3306}"
    local user="${MARIADB_USER:-indi_allsky_own}"
    local pass="${MARIADB_PASSWORD:-}"
    if [ "$pass" = "CHANGE_ME_DATABASE_PASSWORD" ] || [ "$pass" = "indi_allsky_db_pass" ]; then
        echo "WARNING: Using default/placeholder MARIADB_PASSWORD! Please update .env with a secure password." >&2
    fi
    local retries=30

    echo "Connecting to MariaDB at ${host}:${port}..."
    local i=0
    while ! mariadb-admin ping -h"${host}" -P"${port}" -u"${user}" -p"${pass}" --silent 2>/dev/null; do
        i=$((i + 1))
        if [ "$i" -ge "$retries" ]; then
            echo "Warning: Database connection timed out after 60s. Continuing..."
            break
        fi
        sleep 2
    done
    echo "Database ready."
}

start_indiserver() {
    local indiserver_bin="/usr/bin/indiserver"
    [ -f "/usr/local/bin/indiserver" ] && indiserver_bin="/usr/local/bin/indiserver"

    local ccd_driver="${INDIALLSKY_INDI_CCD_DRIVER:-indi_simulator_ccd}"
    local gps_driver="${INDIALLSKY_INDI_GPS_DRIVER:-}"
    local port="${INDIALLSKY_INDI_PORT:-7624}"

    local drivers=("indi_simulator_telescope" "$ccd_driver")
    if [ -n "$gps_driver" ] && [ "$gps_driver" != "None" ]; then
        drivers+=("$gps_driver")
    fi

    echo "Starting indiserver on port ${port} with drivers: ${drivers[*]}"
    run_as_app_user "$indiserver_bin" -v -p "$port" "${drivers[@]}"
}

start_gunicorn() {
    generate_flask_json
    bootstrap_ssl_certificates
    bootstrap_nginx_conf
    bootstrap_mosquitto_conf
    wait_for_database

    cd "$ALLSKY_DIRECTORY"
    export FLASK_APP=app.py

    # Legacy migration layout compatibility: In previous Docker stacks, migrations_indi_allsky was mounted
    # to /var/lib/indi-allsky rather than /var/lib/indi-allsky/migrations, creating a nested 'migrations' directory.
    if [ -d "${MIGRATION_FOLDER}/migrations" ] && [ ! -f "${MIGRATION_FOLDER}/alembic.ini" ]; then
        echo "Consolidating legacy migrations directory layout..."
        shopt -s dotglob 2>/dev/null || true
        mv "${MIGRATION_FOLDER}"/migrations/* "${MIGRATION_FOLDER}"/ 2>/dev/null || true
        rmdir "${MIGRATION_FOLDER}"/migrations 2>/dev/null || true
    fi

    if [ ! -d "$MIGRATION_FOLDER" ] || [ ! -f "$MIGRATION_FOLDER/alembic.ini" ]; then
        echo "Initializing database migration repository in ${MIGRATION_FOLDER}..."
        flask db init -d "$MIGRATION_FOLDER"
    fi

    echo "Checking database migration revisions..."
    flask db revision --autogenerate -d "$MIGRATION_FOLDER" -m "docker_auto" 2>/dev/null || true
    echo "Applying database migrations..."
    flask db upgrade head -d "$MIGRATION_FOLDER"

    # Bootstrap default configuration
    echo "Bootstrapping database configuration..."
    ./config.py bootstrap --image_folder "$IMAGE_FOLDER"

    # Update database IMAGE_FOLDER config
    local tmp_cfg
    tmp_cfg=$(mktemp --suffix=.json)
    if ./config.py dump > "$tmp_cfg" 2>/dev/null && [ -s "$tmp_cfg" ]; then
        local tmp_mod
        tmp_mod=$(mktemp --suffix=.json)
        jq --arg img "$IMAGE_FOLDER" '.IMAGE_FOLDER = $img' "$tmp_cfg" > "$tmp_mod"
        ./config.py load -c "$tmp_mod" --force 2>/dev/null || true
        rm -f "$tmp_cfg" "$tmp_mod"
    fi

    # Provision initial admin user if needed
    local user_count
    user_count=$(./config.py user_count 2>/dev/null || echo "0")
    if [ "$user_count" -le 1 ] && [ -n "${INDIALLSKY_WEB_USER:-}" ]; then
        local web_pass="${INDIALLSKY_WEB_PASS:-}"
        if [ "$web_pass" = "CHANGE_ME_ADMIN_PASSWORD" ] || [ "$web_pass" = "adminpassword" ]; then
            echo "WARNING: Using default/placeholder INDIALLSKY_WEB_PASS! Please update .env with a secure password." >&2
        fi
        if [ -n "$web_pass" ] && [ "${#web_pass}" -ge 8 ]; then
            echo "Creating initial admin user '${INDIALLSKY_WEB_USER}'..."
            USERTOOL_PASSWORD="$web_pass" python3 misc/usertool.py adduser \
                -u "$INDIALLSKY_WEB_USER" \
                -p "$web_pass" \
                -f "${INDIALLSKY_WEB_NAME:-Admin User}" \
                -e "${INDIALLSKY_WEB_EMAIL:-admin@example.org}" 2>/dev/null || true
            python3 misc/usertool.py setadmin -u "$INDIALLSKY_WEB_USER" 2>/dev/null || true
        else
            echo "Skipping admin user creation (INDIALLSKY_WEB_PASS must be at least 8 characters)." >&2
        fi
    fi

    if [ "${INDIALLSKY_WEB_GENERATE_APIKEY:-false}" = "true" ] && [ -n "${INDIALLSKY_WEB_USER:-}" ]; then
        python3 misc/usertool.py genapikey -u "$INDIALLSKY_WEB_USER" 2>/dev/null || true
    fi

    chown -R indi-allsky:indi-allsky "$ALLSKY_ETC" "$DB_FOLDER" 2>/dev/null || true
    chmod -R a+r "$ALLSKY_ETC" 2>/dev/null || true
    chmod 755 "$ALLSKY_ETC" "${ALLSKY_ETC}/certs" 2>/dev/null || true
    chown -R indi-allsky:www-data "$DOCROOT_FOLDER" 2>/dev/null || true

    export GUNICORN_ERROR_LOG_HANDLER=wsgi
    export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

    echo "Starting Gunicorn application server..."
    run_as_app_user gunicorn \
        --bind 0.0.0.0:8000 \
        --worker-class gthread \
        --threads "${GUNICORN_THREADS:-8}" \
        --timeout "${GUNICORN_TIMEOUT:-180}" \
        --umask 0022 \
        --log-level "${GUNICORN_LOG_LEVEL:-info}" \
        indi_allsky.wsgi
}

start_capture() {
    generate_flask_json
    wait_for_database

    cd "$ALLSKY_DIRECTORY"

    # Wait for database schema and config table to be bootstrapped by gunicorn
    echo "Waiting for database configuration bootstrap..."
    local retries=30
    local i=0
    local tmp_cfg
    tmp_cfg=$(mktemp --suffix=.json)
    while ! ./config.py dump > "$tmp_cfg" 2>/dev/null || [ ! -s "$tmp_cfg" ]; do
        i=$((i + 1))
        if [ "$i" -ge "$retries" ]; then
            echo "Warning: Timed out waiting for config table. Continuing..."
            break
        fi
        sleep 2
    done

    # Adjust INDI_SERVER and MQTT host/credentials in database config to target Docker service names
    if [ -s "$tmp_cfg" ]; then
        local tmp_mod
        tmp_mod=$(mktemp --suffix=.json)
        local mqtt_user="${INDIALLSKY_MOSQUITTO_USER:-}"
        local mqtt_pass="${INDIALLSKY_MOSQUITTO_PASS:-}"
        jq \
            --arg img "$IMAGE_FOLDER" \
            --arg indi_srv "${INDIALLSKY_INDI_SERVER:-indiserver.indi.allsky}" \
            --arg mqtt_host "${INDIALLSKY_MQTT_HOST:-mosquitto.indi.allsky}" \
            --arg mqtt_user "$mqtt_user" \
            --arg mqtt_pass "$mqtt_pass" \
            '
            .IMAGE_FOLDER = $img |
            (if .INDI_SERVER == "localhost" or .INDI_SERVER == "127.0.0.1" then .INDI_SERVER = $indi_srv else . end) |
            (if .MQTTPUBLISH.HOST == "localhost" or .MQTTPUBLISH.HOST == "127.0.0.1" then .MQTTPUBLISH.HOST = $mqtt_host else . end) |
            (if ($mqtt_user != "") and (.MQTTPUBLISH.USERNAME == "indi-allsky" or .MQTTPUBLISH.USERNAME == "" or .MQTTPUBLISH.USERNAME == null) then .MQTTPUBLISH.USERNAME = $mqtt_user else . end) |
            (if ($mqtt_pass != "") and (.MQTTPUBLISH.PASSWORD == "" or .MQTTPUBLISH.PASSWORD == null) then .MQTTPUBLISH.PASSWORD = $mqtt_pass else . end)
            ' "$tmp_cfg" > "$tmp_mod"
        ./config.py load -c "$tmp_mod" --force 2>/dev/null || true
        rm -f "$tmp_mod"
    fi
    rm -f "$tmp_cfg"

    chown -R indi-allsky:indi-allsky "$ALLSKY_ETC" "$DB_FOLDER" 2>/dev/null || true
    if [ "$(stat -c '%U' "$DOCROOT_FOLDER" 2>/dev/null)" != "indi-allsky" ]; then
        chown -R indi-allsky:www-data "$DOCROOT_FOLDER" 2>/dev/null || true
    fi

    if [ "${INDIALLSKY_DARK_CAPTURE_ENABLE:-false}" = "true" ]; then
        echo "Starting dark frame capture..."
        local dark_args=("--bitmax" "${INDIALLSKY_DARK_CAPTURE_BITMAX:-16}")
        [ -n "${INDIALLSKY_DARK_CAPTURE_DAYTIME:-}" ] && dark_args+=("${INDIALLSKY_DARK_CAPTURE_DAYTIME}")
        dark_args+=("${INDIALLSKY_DARK_CAPTURE_MODE:-average}")
        run_as_app_user ./darks.py "${dark_args[@]}"
    else
        echo "Starting indi-allsky capture loop..."
        run_as_app_user ./allsky.py --log stderr run
    fi
}

case "${1:-}" in
    indiserver)
        start_indiserver
        ;;
    gunicorn)
        start_gunicorn
        ;;
    capture)
        start_capture
        ;;
    *)
        generate_flask_json
        run_as_app_user "$@"
        ;;
esac
